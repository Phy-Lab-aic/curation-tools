"""Cycle-boundary detection and stamping helpers for gripper state traces."""

from __future__ import annotations

import logging
import os
from glob import glob
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

LEFT_GRIPPER_IDX = 7
RIGHT_GRIPPER_IDX = 15
CLOSED_THRESHOLD = 0.5
OPEN_THRESHOLD = 0.8
_TERMINAL_COL = "is_terminal"
_LAST_COL = "is_last"

logger = logging.getLogger(__name__)


def _detect_arm_cycle_ends(gripper_values: np.ndarray) -> list[int]:
    """Return frame indices where one gripper finishes a close-to-open cycle."""
    if gripper_values.size == 0:
        return []

    cycle_ends: list[int] = []
    searching_for_open = bool(gripper_values[0] < CLOSED_THRESHOLD)

    for frame_idx, value in enumerate(gripper_values):
        if searching_for_open:
            if value > OPEN_THRESHOLD:
                cycle_ends.append(frame_idx)
                searching_for_open = False
        elif value < CLOSED_THRESHOLD:
            searching_for_open = True

    return cycle_ends


def detect_cycle_ends(states: np.ndarray) -> list[int]:
    """Detect and merge cycle-end frame indices from the left and right grippers."""
    left_cycle_ends = _detect_arm_cycle_ends(states[:, LEFT_GRIPPER_IDX])
    right_cycle_ends = _detect_arm_cycle_ends(states[:, RIGHT_GRIPPER_IDX])
    return sorted(set(left_cycle_ends + right_cycle_ends))


def _data_parquet_files(dataset_root: Path) -> list[Path]:
    """Return all dataset data parquet files in a deterministic order."""
    pattern = str(dataset_root / "data" / "chunk-*" / "file-*.parquet")
    return [Path(path) for path in sorted(glob(pattern))]


def _stamped_data_parquet_files(parquet_files: list[Path]) -> list[Path]:
    """Return parquet files that already carry either cycle-stamp column."""
    stamped_files: list[Path] = []
    for parquet_path in parquet_files:
        schema = pq.read_schema(parquet_path)
        if _TERMINAL_COL in schema.names or _LAST_COL in schema.names:
            stamped_files.append(parquet_path)
    return stamped_files


def describe_stamp_state(dataset_path: Path | str) -> dict:
    """Probe dataset parquet schemas to determine whether cycle stamps already exist."""
    dataset_root = Path(dataset_path)
    parquet_files = _data_parquet_files(dataset_root)
    if not parquet_files:
        return {"stamped": False, "is_terminal_count_sample": 0}

    stamped_files = _stamped_data_parquet_files(parquet_files)
    if not stamped_files:
        return {"stamped": False, "is_terminal_count_sample": 0}

    sample_path = stamped_files[0]
    sample_schema = pq.read_schema(sample_path)
    if _TERMINAL_COL not in sample_schema.names:
        return {"stamped": True, "is_terminal_count_sample": 0}

    sample = pq.read_table(sample_path, columns=[_TERMINAL_COL])
    count = sum(bool(value) for value in sample.column(_TERMINAL_COL).to_pylist())
    return {"stamped": True, "is_terminal_count_sample": count}


def stamp_dataset_cycles(dataset_path: Path | str, *, overwrite: bool) -> dict:
    """Stamp every data parquet row with terminal and last-frame markers."""
    dataset_root = Path(dataset_path)
    parquet_files = _data_parquet_files(dataset_root)
    if not parquet_files:
        raise FileNotFoundError(f"No data parquet files found under {dataset_root}")

    stamped_files = _stamped_data_parquet_files(parquet_files)
    if stamped_files and not overwrite:
        raise ValueError("already_stamped")

    episode_rows: dict[int, list[tuple[int, int, Path, int, list[float]]]] = {}
    file_terminal_flags: dict[Path, list[bool]] = {}
    file_last_flags: dict[Path, list[bool]] = {}
    physical_row_sequence = 0

    for parquet_path in parquet_files:
        table = pq.read_table(parquet_path, columns=["episode_index", "frame_index", "observation.state"])
        episode_indices = [int(value) for value in table.column("episode_index").to_pylist()]
        frame_indices = [int(value) for value in table.column("frame_index").to_pylist()]
        states = table.column("observation.state").to_pylist()

        file_terminal_flags[parquet_path] = [False] * len(episode_indices)
        file_last_flags[parquet_path] = [False] * len(episode_indices)

        for row_index, (episode_index, frame_index, state) in enumerate(
            zip(episode_indices, frame_indices, states, strict=True)
        ):
            episode_rows.setdefault(episode_index, []).append(
                (frame_index, physical_row_sequence, parquet_path, row_index, state)
            )
            physical_row_sequence += 1

    is_terminal_count = 0
    is_last_count = 0

    for episode_index, rows in sorted(episode_rows.items()):
        ordered_rows = sorted(rows, key=lambda row: (row[0], row[1]))
        states = np.asarray([row[4] for row in ordered_rows], dtype=np.float32)

        for local_index in detect_cycle_ends(states):
            _, _, parquet_path, row_index, _ = ordered_rows[local_index]
            file_terminal_flags[parquet_path][row_index] = True
            is_terminal_count += 1

        if ordered_rows:
            _, _, parquet_path, row_index, _ = ordered_rows[-1]
            file_last_flags[parquet_path][row_index] = True
            is_last_count += 1

    for parquet_path in parquet_files:
        table = pq.read_table(parquet_path)
        if overwrite:
            for column_name in (_TERMINAL_COL, _LAST_COL):
                column_index = table.schema.get_field_index(column_name)
                if column_index >= 0:
                    table = table.remove_column(column_index)

        table = table.append_column(_TERMINAL_COL, pa.array(file_terminal_flags[parquet_path], type=pa.bool_()))
        table = table.append_column(_LAST_COL, pa.array(file_last_flags[parquet_path], type=pa.bool_()))

        tmp_path = parquet_path.with_suffix(f"{parquet_path.suffix}.tmp")
        try:
            pq.write_table(table, tmp_path)
            os.replace(tmp_path, parquet_path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    logger.info(
        "Stamped dataset cycles for %s: episodes=%d terminal=%d last=%d",
        dataset_root,
        len(episode_rows),
        is_terminal_count,
        is_last_count,
    )
    return {
        "episodes_processed": len(episode_rows),
        "is_terminal_count": is_terminal_count,
        "is_last_count": is_last_count,
    }
