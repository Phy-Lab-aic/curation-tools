"""Service for scanning mount roots and discovering cell/dataset structure.

A "cell" is a subdirectory of an allowed_dataset_root whose name matches
the configured pattern (default: "cell*"). A dataset inside a cell is any
subdirectory that contains meta/info.json.
"""

from __future__ import annotations

import fnmatch
import json
import logging
from pathlib import Path

from backend.models.schemas import CellInfo, DatasetSummary

logger = logging.getLogger(__name__)


def scan_cells(roots: list[str], pattern: str = "cell*") -> list[CellInfo]:
    """Scan all roots for cell directories matching pattern.

    Args:
        roots: List of mount root paths (from allowed_dataset_roots).
        pattern: Glob pattern for cell directory names (default "cell*").

    Returns:
        List of CellInfo sorted by (root, name).
    """
    cells: list[CellInfo] = []
    for root_str in roots:
        root = Path(root_str)
        if not root.exists() or not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if not fnmatch.fnmatch(child.name, pattern):
                continue
            dataset_count = _count_datasets(child)
            cells.append(CellInfo(
                name=child.name,
                path=str(child.resolve()),
                mount_root=str(root.resolve()),
                dataset_count=dataset_count,
                active=True,
            ))
    return cells


def get_datasets_in_cell(cell_path: str) -> list[DatasetSummary]:
    """Return all datasets inside a cell directory.

    A dataset is a subdirectory containing meta/info.json.
    graded_count is 0 for now — computed from sidecar in a future step.
    """
    root = Path(cell_path)
    if not root.exists() or not root.is_dir():
        return []

    datasets: list[DatasetSummary] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        info_path = child / "meta" / "info.json"
        if not info_path.exists():
            continue
        try:
            info = json.loads(info_path.read_text(encoding="utf-8").rstrip("\x00"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Cannot read %s: %s", info_path, e)
            continue
        datasets.append(DatasetSummary(
            name=child.name,
            path=str(child.resolve()),
            total_episodes=info.get("total_episodes", 0),
            graded_count=0,
            robot_type=info.get("robot_type"),
            fps=info.get("fps", 0),
        ))
    return datasets


def _count_datasets(cell_dir: Path) -> int:
    """Count subdirectories of cell_dir that have meta/info.json."""
    return sum(
        1 for child in cell_dir.iterdir()
        if child.is_dir() and (child / "meta" / "info.json").exists()
    )
