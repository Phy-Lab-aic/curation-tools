"""Service for managing dataset fields (info.json + episode parquet columns).

info.json system fields are read-only. Custom fields can be added, edited, deleted.
Adding a parquet column requires rewriting all parquet files in the dataset.
"""

from __future__ import annotations

import json
import logging
from glob import glob
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

SYSTEM_INFO_KEYS = {
    "fps", "total_episodes", "total_tasks", "robot_type", "features",
    "total_frames", "total_chunks", "chunks_size", "data_path",
    "videos_path", "splits",
}

SYSTEM_EPISODE_COLUMNS = {
    "episode_index", "length", "task_index", "chunk_index", "file_index",
    "dataset_from_index", "dataset_to_index", "task_instruction",
}

DTYPE_MAP = {
    "string": pa.string(),
    "int64": pa.int64(),
    "float64": pa.float64(),
    "bool": pa.bool_(),
}


def get_info_fields(dataset_path: str) -> list[dict]:
    """Return all fields from info.json with system/custom classification."""
    info = _read_info(dataset_path)
    fields = []
    for key, value in info.items():
        fields.append({
            "key": key,
            "value": value,
            "dtype": type(value).__name__,
            "is_system": key in SYSTEM_INFO_KEYS,
        })
    return fields


def update_info_field(dataset_path: str, key: str, value: str | int | float | bool) -> None:
    """Update or add a custom field in info.json. System fields are rejected."""
    if key in SYSTEM_INFO_KEYS:
        raise ValueError(f"Cannot modify system field: {key}")
    info = _read_info(dataset_path)
    info[key] = value
    _write_info(dataset_path, info)


def delete_info_field(dataset_path: str, key: str) -> None:
    """Delete a custom field from info.json. System fields are rejected."""
    if key in SYSTEM_INFO_KEYS:
        raise ValueError(f"Cannot delete system field: {key}")
    info = _read_info(dataset_path)
    info.pop(key, None)
    _write_info(dataset_path, info)


def get_episode_columns(dataset_path: str) -> list[dict]:
    """Return all columns from episode parquet with system/custom classification."""
    root = Path(dataset_path)
    parquet_files = sorted(glob(str(root / "meta" / "episodes" / "chunk-*" / "file-*.parquet")))
    if not parquet_files:
        return []
    schema = pq.read_schema(parquet_files[0])
    columns = []
    for i in range(len(schema)):
        field = schema.field(i)
        columns.append({
            "name": field.name,
            "dtype": str(field.type),
            "is_system": field.name in SYSTEM_EPISODE_COLUMNS,
        })
    return columns


def add_episode_column(
    dataset_path: str,
    column_name: str,
    dtype: str,
    default_value: str | int | float | bool,
) -> None:
    """Add a new column to all episode parquet files. Rewrites every file."""
    root = Path(dataset_path)
    parquet_files = sorted(glob(str(root / "meta" / "episodes" / "chunk-*" / "file-*.parquet")))
    if not parquet_files:
        raise ValueError("No episode parquet files found")

    schema = pq.read_schema(parquet_files[0])
    if column_name in schema.names:
        raise ValueError(f"Column '{column_name}' already exists")

    arrow_type = DTYPE_MAP.get(dtype)
    if arrow_type is None:
        raise ValueError(f"Unsupported dtype: {dtype}. Use: {', '.join(DTYPE_MAP.keys())}")

    for f in parquet_files:
        file_path = Path(f)
        table = pq.read_table(str(file_path))
        new_col = pa.array([default_value] * table.num_rows, type=arrow_type)
        table = table.append_column(column_name, new_col)
        pq.write_table(table, str(file_path))
        logger.info("Added column '%s' to %s (%d rows)", column_name, file_path, table.num_rows)


def _read_info(dataset_path: str) -> dict:
    info_path = Path(dataset_path) / "meta" / "info.json"
    content = info_path.read_text(encoding="utf-8").rstrip("\x00")
    return json.loads(content)


def _write_info(dataset_path: str, info: dict) -> None:
    info_path = Path(dataset_path) / "meta" / "info.json"
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
