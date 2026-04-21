"""Verify the shared mock-dataset helper now includes Serial_number."""

from pathlib import Path

import pyarrow.parquet as pq


def test_mock_dataset_has_serial_number(tmp_path: Path):
    from tests.test_episode_annotations_db import _create_mock_dataset
    ds = _create_mock_dataset(tmp_path)
    pf = ds / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
    schema = pq.read_schema(pf)
    assert "Serial_number" in schema.names
    t = pq.read_table(pf, columns=["episode_index", "Serial_number"])
    serials = t.column("Serial_number").to_pylist()
    assert all(s and s.startswith("MOCK_") for s in serials)
    assert len(set(serials)) == len(serials), "serials must be unique per episode"
