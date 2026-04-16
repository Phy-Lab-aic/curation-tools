import json
from pathlib import Path

import pytest

from backend.services.cell_service import scan_cells, get_datasets_in_cell


@pytest.fixture
def mock_mount(tmp_path: Path):
    """Create a fake mount structure:
    tmp_path/
      cell001/
        dataset_a/meta/info.json
        dataset_b/meta/info.json
      cell002/
        dataset_c/meta/info.json
      not_a_cell/          <- no cell* prefix, should be ignored
        dataset_d/meta/info.json
    """
    for cell, datasets in [
        ("cell001", ["dataset_a", "dataset_b"]),
        ("cell002", ["dataset_c"]),
    ]:
        for ds in datasets:
            info = {
                "fps": 30,
                "total_episodes": 10,
                "robot_type": "ur5e",
                "features": {},
                "total_tasks": 2,
            }
            p = tmp_path / cell / ds / "meta"
            p.mkdir(parents=True)
            (p / "info.json").write_text(json.dumps(info))

    # Not a cell — should be ignored
    other = tmp_path / "not_a_cell" / "dataset_d" / "meta"
    other.mkdir(parents=True)
    (other / "info.json").write_text("{}")

    return tmp_path


def test_scan_cells_finds_cell_dirs(mock_mount):
    cells = scan_cells([str(mock_mount)], pattern="cell*")
    names = {c.name for c in cells}
    assert names == {"cell001", "cell002"}


def test_scan_cells_ignores_non_cell_dirs(mock_mount):
    cells = scan_cells([str(mock_mount)], pattern="cell*")
    names = {c.name for c in cells}
    assert "not_a_cell" not in names


def test_scan_cells_counts_datasets(mock_mount):
    cells = scan_cells([str(mock_mount)], pattern="cell*")
    cell_map = {c.name: c for c in cells}
    assert cell_map["cell001"].dataset_count == 2
    assert cell_map["cell002"].dataset_count == 1


def test_scan_cells_marks_active(mock_mount):
    cells = scan_cells([str(mock_mount)], pattern="cell*")
    assert all(c.active for c in cells)


def test_scan_cells_nonexistent_root():
    """A root that doesn't exist returns no cells (no error)."""
    cells = scan_cells(["/nonexistent/path"], pattern="cell*")
    assert cells == []


def test_get_datasets_in_cell(mock_mount):
    datasets = get_datasets_in_cell(str(mock_mount / "cell001"))
    names = {d.name for d in datasets}
    assert names == {"dataset_a", "dataset_b"}


def test_get_datasets_reads_fps(mock_mount):
    datasets = get_datasets_in_cell(str(mock_mount / "cell001"))
    assert all(d.fps == 30 for d in datasets)
