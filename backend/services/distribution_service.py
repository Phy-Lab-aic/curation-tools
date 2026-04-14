"""Service for computing column distributions from episode parquet files.

Uses pyarrow column projection to read only the selected field,
keeping memory usage low even for large datasets.
"""

from __future__ import annotations

import logging
from glob import glob
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from backend.models.schemas import DistributionBin, DistributionResponse, FieldInfo

logger = logging.getLogger(__name__)

SYSTEM_COLUMNS = {
    "episode_index", "length", "task_index", "chunk_index", "file_index",
    "dataset_from_index", "dataset_to_index", "task_instruction",
}


def get_available_fields(dataset_path: str) -> list[FieldInfo]:
    """Return all columns available in episode parquet files."""
    root = Path(dataset_path)
    parquet_files = sorted(glob(str(root / "meta" / "episodes" / "chunk-*" / "file-*.parquet")))
    if not parquet_files:
        return []

    schema = pq.read_schema(parquet_files[0])
    fields: list[FieldInfo] = []
    for i in range(len(schema)):
        field = schema.field(i)
        dtype = _arrow_type_to_str(field.type)
        fields.append(FieldInfo(
            name=field.name,
            dtype=dtype,
            is_system=field.name in SYSTEM_COLUMNS,
        ))
    return fields


def compute_distribution(
    dataset_path: str,
    field: str,
    chart_type: str = "auto",
) -> DistributionResponse:
    """Compute value distribution for a single column using column projection."""
    root = Path(dataset_path)
    parquet_files = sorted(glob(str(root / "meta" / "episodes" / "chunk-*" / "file-*.parquet")))
    if not parquet_files:
        raise ValueError(f"No episode parquet files found in {root}")

    tables: list[pa.Table] = []
    for f in parquet_files:
        schema = pq.read_schema(f)
        if field not in schema.names:
            raise ValueError(f"Field '{field}' not found in parquet schema")
        table = pq.read_table(f, columns=[field])
        tables.append(table)

    combined = pa.concat_tables(tables, promote_options="default")
    column = combined.column(field)
    total = len(column)
    dtype = _arrow_type_to_str(column.type)

    if chart_type == "auto":
        chart_type = "histogram" if _is_numeric(column.type) else "bar"

    if chart_type == "histogram":
        bins = _histogram_bins(column)
    else:
        bins = _categorical_bins(column)

    return DistributionResponse(
        field=field,
        dtype=dtype,
        chart_type=chart_type,
        bins=bins,
        total=total,
    )


def _is_numeric(arrow_type: pa.DataType) -> bool:
    return pa.types.is_integer(arrow_type) or pa.types.is_floating(arrow_type)


def _histogram_bins(column: pa.ChunkedArray, num_bins: int = 20) -> list[DistributionBin]:
    arr = column.to_pylist()
    valid = [v for v in arr if v is not None]
    if not valid:
        return []

    min_val = min(valid)
    max_val = max(valid)

    if min_val == max_val:
        return [DistributionBin(label=str(min_val), count=len(valid))]

    bin_width = (max_val - min_val) / num_bins
    bins: list[DistributionBin] = []
    for i in range(num_bins):
        lo = min_val + i * bin_width
        hi = lo + bin_width
        count = sum(1 for v in valid if lo <= v < hi) if i < num_bins - 1 \
            else sum(1 for v in valid if lo <= v <= hi)
        if count > 0:
            label = f"{lo:.1f}-{hi:.1f}" if isinstance(lo, float) else f"{int(lo)}-{int(hi)}"
            bins.append(DistributionBin(label=label, count=count))
    return bins


def _categorical_bins(column: pa.ChunkedArray) -> list[DistributionBin]:
    arr = column.to_pylist()
    counts: dict[str, int] = {}
    for v in arr:
        key = str(v) if v is not None else "(null)"
        counts[key] = counts.get(key, 0) + 1

    return [
        DistributionBin(label=k, count=v)
        for k, v in sorted(counts.items(), key=lambda x: -x[1])
    ]


def _arrow_type_to_str(t: pa.DataType) -> str:
    if pa.types.is_int64(t):
        return "int64"
    if pa.types.is_int32(t):
        return "int32"
    if pa.types.is_float64(t):
        return "float64"
    if pa.types.is_float32(t):
        return "float32"
    if pa.types.is_boolean(t):
        return "bool"
    if pa.types.is_string(t) or pa.types.is_large_string(t):
        return "string"
    return str(t)
