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


def describe_stamp_state(dataset_path: Path | str) -> dict:
    """Probe the first parquet file to determine whether cycle stamps already exist."""
    dataset_root = Path(dataset_path)
    parquet_files = _data_parquet_files(dataset_root)
    if not parquet_files:
        return {"stamped": False, "is_terminal_count_sample": 0}

    schema = pq.read_schema(parquet_files[0])
    if _TERMINAL_COL not in schema.names:
        return {"stamped": False, "is_terminal_count_sample": 0}

    sample = pq.read_table(parquet_files[0], columns=[_TERMINAL_COL])
    count = sum(bool(value) for value in sample.column(_TERMINAL_COL).to_pylist())
    return {"stamped": True, "is_terminal_count_sample": count}


def stamp_dataset_cycles(dataset_path: Path | str, *, overwrite: bool) -> dict:
    """Stamp every data parquet row with terminal and last-frame markers."""
    dataset_root = Path(dataset_path)
    parquet_files = _data_parquet_files(dataset_root)
    if not parquet_files:
        raise FileNotFoundError(f"No data parquet files found under {dataset_root}")

    stamp_state = describe_stamp_state(dataset_root)
    if stamp_state["stamped"] and not overwrite:
        raise ValueError("already_stamped")

    file_episode_rows: dict[Path, list[int]] = {}
    episode_states: dict[int, list[list[float]]] = {}

    for parquet_path in parquet_files:
        table = pq.read_table(parquet_path, columns=["episode_index", "observation.state"])
        episode_indices = [int(value) for value in table.column("episode_index").to_pylist()]
        states = table.column("observation.state").to_pylist()
        file_episode_rows[parquet_path] = episode_indices

        for episode_index, state in zip(episode_indices, states):
            episode_states.setdefault(episode_index, []).append(state)

    episode_terminal_flags: dict[int, list[bool]] = {}
    episode_last_flags: dict[int, list[bool]] = {}
    is_terminal_count = 0
    is_last_count = 0

    for episode_index, rows in sorted(episode_states.items()):
        states = np.asarray(rows, dtype=np.float32)
        terminal_flags = np.zeros(len(states), dtype=bool)
        for frame_index in detect_cycle_ends(states):
            terminal_flags[frame_index] = True

        last_flags = np.zeros(len(states), dtype=bool)
        if len(states):
            last_flags[-1] = True

        terminal_list = terminal_flags.tolist()
        last_list = last_flags.tolist()
        episode_terminal_flags[episode_index] = terminal_list
        episode_last_flags[episode_index] = last_list
        is_terminal_count += int(sum(terminal_list))
        is_last_count += int(sum(last_list))

    episode_offsets = {episode_index: 0 for episode_index in episode_states}

    for parquet_path in parquet_files:
        table = pq.read_table(parquet_path)
        if overwrite:
            for column_name in (_TERMINAL_COL, _LAST_COL):
                column_index = table.schema.get_field_index(column_name)
                if column_index >= 0:
                    table = table.remove_column(column_index)

        file_terminal_flags: list[bool] = []
        file_last_flags: list[bool] = []
        for episode_index in file_episode_rows[parquet_path]:
            offset = episode_offsets[episode_index]
            file_terminal_flags.append(episode_terminal_flags[episode_index][offset])
            file_last_flags.append(episode_last_flags[episode_index][offset])
            episode_offsets[episode_index] += 1

        table = table.append_column(_TERMINAL_COL, pa.array(file_terminal_flags, type=pa.bool_()))
        table = table.append_column(_LAST_COL, pa.array(file_last_flags, type=pa.bool_()))

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
        len(episode_states),
        is_terminal_count,
        is_last_count,
    )
    return {
        "episodes_processed": len(episode_states),
        "is_terminal_count": is_terminal_count,
        "is_last_count": is_last_count,
    }
