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
        fps = info.get("fps", 0)
        grade_stats = _count_grades(child, fps)
        graded = int(grade_stats["good"]) + int(grade_stats["normal"]) + int(grade_stats["bad"])
        datasets.append(DatasetSummary(
            name=child.name,
            path=str(child.resolve()),
            total_episodes=info.get("total_episodes", 0),
            graded_count=graded,
            good_count=int(grade_stats["good"]),
            normal_count=int(grade_stats["normal"]),
            bad_count=int(grade_stats["bad"]),
            robot_type=info.get("robot_type"),
            fps=fps,
            total_duration_sec=float(grade_stats["total_duration_sec"]),
            good_duration_sec=float(grade_stats["good_duration_sec"]),
            normal_duration_sec=float(grade_stats["normal_duration_sec"]),
            bad_duration_sec=float(grade_stats["bad_duration_sec"]),
        ))
    return datasets


def _count_grades(dataset_dir: Path, fps: int = 0) -> dict[str, int | float]:
    """Count grades and durations from parquet files and sidecar JSON (sidecar wins)."""
    from glob import glob
    import pyarrow.parquet as pq
    from backend.services.episode_service import _load_sidecar

    counts: dict[str, int | float] = {"good": 0, "normal": 0, "bad": 0}

    # 1. Read grades and lengths from parquet
    episode_grades: dict[int, str | None] = {}
    episode_lengths: dict[int, int] = {}
    parquet_files = sorted(glob(str(dataset_dir / "meta" / "episodes" / "chunk-*" / "file-*.parquet")))
    for f in parquet_files:
        schema = pq.read_schema(f)
        cols = ["episode_index"]
        has_grade = "grade" in schema.names
        has_length = "length" in schema.names
        if has_grade:
            cols.append("grade")
        if has_length:
            cols.append("length")
        table = pq.read_table(f, columns=cols)
        indices = table.column("episode_index").to_pylist()
        grades = table.column("grade").to_pylist() if has_grade else [None] * len(indices)
        lengths = table.column("length").to_pylist() if has_length else [0] * len(indices)
        for idx, g, length in zip(indices, grades, lengths):
            episode_grades[idx] = g
            episode_lengths[idx] = length or 0

    # 2. Overlay sidecar (takes priority)
    sidecar = _load_sidecar(dataset_dir)
    for ep_idx_str, ann in sidecar.items():
        grade = ann.get("grade")
        if grade is not None:
            episode_grades[int(ep_idx_str)] = grade

    # 3. Count grades and compute durations
    total_frames = 0
    grade_frames: dict[str, int] = {"good": 0, "normal": 0, "bad": 0}
    for ep_idx, grade in episode_grades.items():
        length = episode_lengths.get(ep_idx, 0)
        total_frames += length
        if grade:
            normalized = grade.strip().lower()
            if normalized in counts:
                counts[normalized] += 1
            if normalized in grade_frames:
                grade_frames[normalized] += length

    divisor = fps if fps > 0 else 1
    counts["total_duration_sec"] = total_frames / divisor
    counts["good_duration_sec"] = grade_frames["good"] / divisor
    counts["normal_duration_sec"] = grade_frames["normal"] / divisor
    counts["bad_duration_sec"] = grade_frames["bad"] / divisor

    return counts


def _count_datasets(cell_dir: Path) -> int:
    """Count subdirectories of cell_dir that have meta/info.json."""
    return sum(
        1 for child in cell_dir.iterdir()
        if child.is_dir() and (child / "meta" / "info.json").exists()
    )
