"""Tests for dataset_ops_engine — direct parquet/video/meta manipulation."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


# ---------------------------------------------------------------------------
# Fixture: create a minimal LeRobot v3.0 dataset on disk
# ---------------------------------------------------------------------------

def _make_episode_table(episodes: list[dict], camera_keys: list[str]) -> pa.Table:
    """Build an episodes parquet table from a list of episode dicts."""
    fields = {
        "episode_index": pa.array([e["episode_index"] for e in episodes], type=pa.int64()),
        "tasks": pa.array([e.get("tasks", ["task0"]) for e in episodes], type=pa.list_(pa.string())),
        "length": pa.array([e["length"] for e in episodes], type=pa.int64()),
        "dataset_from_index": pa.array([e["dataset_from_index"] for e in episodes], type=pa.int64()),
        "dataset_to_index": pa.array([e["dataset_to_index"] for e in episodes], type=pa.int64()),
        "data/chunk_index": pa.array([e["data/chunk_index"] for e in episodes], type=pa.int64()),
        "data/file_index": pa.array([e["data/file_index"] for e in episodes], type=pa.int64()),
        "Serial_number": pa.array([e.get("Serial_number", f"SN_{e['episode_index']}") for e in episodes], type=pa.large_string()),
        "tags": pa.array([e.get("tags", []) for e in episodes], type=pa.list_(pa.string())),
        "grade": pa.array([e.get("grade") for e in episodes], type=pa.large_string()),
    }
    for cam in camera_keys:
        fields[f"videos/{cam}/chunk_index"] = pa.array([e["data/chunk_index"] for e in episodes], type=pa.int64())
        fields[f"videos/{cam}/file_index"] = pa.array([e["data/file_index"] for e in episodes], type=pa.int64())
        fields[f"videos/{cam}/from_timestamp"] = pa.array([0.0] * len(episodes), type=pa.float64())
        fields[f"videos/{cam}/to_timestamp"] = pa.array([float(e["length"]) / 30.0 for e in episodes], type=pa.float64())
    return pa.table(fields)


def _make_data_parquet(num_frames: int, episode_index: int, task_index: int = 0) -> pa.Table:
    """Build a minimal data parquet for one episode."""
    return pa.table({
        "observation.state": pa.FixedSizeListArray.from_arrays(
            pa.array([0.0] * num_frames * 2, type=pa.float32()), 2
        ),
        "action": pa.FixedSizeListArray.from_arrays(
            pa.array([0.0] * num_frames * 2, type=pa.float32()), 2
        ),
        "timestamp": pa.array([i / 30.0 for i in range(num_frames)], type=pa.float64()),
        "frame_index": pa.array(list(range(num_frames)), type=pa.int64()),
        "episode_index": pa.array([episode_index] * num_frames, type=pa.int64()),
        "index": pa.array(list(range(num_frames)), type=pa.int64()),
        "task_index": pa.array([task_index] * num_frames, type=pa.int64()),
    })


CAMERA_KEYS = ["observation.images.cam_top"]


@pytest.fixture()
def sample_dataset(tmp_path: Path) -> Path:
    """Create a 5-episode dataset with chunks_size=3 (chunk-000: ep 0,1,2; chunk-001: ep 3,4)."""
    root = tmp_path / "test_dataset"
    chunks_size = 3
    episodes = []
    offset = 0
    for i in range(5):
        length = 10 + i
        episodes.append({
            "episode_index": i,
            "tasks": ["Pick up object"],
            "length": length,
            "dataset_from_index": offset,
            "dataset_to_index": offset + length,
            "data/chunk_index": i // chunks_size,
            "data/file_index": i % chunks_size,
            "grade": "good" if i % 2 == 0 else None,
            "Serial_number": f"SN_{i:06d}",
        })
        offset += length

    # meta/info.json
    meta = root / "meta"
    meta.mkdir(parents=True)
    info = {
        "codebase_version": "v3.0",
        "robot_type": "test_robot",
        "total_episodes": 5,
        "total_frames": offset,
        "total_tasks": 1,
        "chunks_size": chunks_size,
        "fps": 30,
        "splits": {"train": "0:5"},
        "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4",
        "features": {
            "observation.state": {"dtype": "float32", "shape": [2], "names": None},
            "action": {"dtype": "float32", "shape": [2], "names": None},
            "timestamp": {"dtype": "float64", "shape": [1], "names": None},
            "frame_index": {"dtype": "int64", "shape": [1], "names": None},
            "episode_index": {"dtype": "int64", "shape": [1], "names": None},
            "index": {"dtype": "int64", "shape": [1], "names": None},
            "task_index": {"dtype": "int64", "shape": [1], "names": None},
            "observation.images.cam_top": {"dtype": "video", "shape": [480, 640, 3], "names": ["height", "width", "channels"], "video_info": {"video.fps": 30}},
        },
    }
    (meta / "info.json").write_text(json.dumps(info, indent=2))

    # meta/tasks.parquet
    tasks_table = pa.table({"task_index": pa.array([0], type=pa.int64())})
    pq.write_table(tasks_table, meta / "tasks.parquet")

    # meta/episodes/ (two chunks)
    for chunk_idx in range(2):
        chunk_dir = meta / "episodes" / f"chunk-{chunk_idx:03d}"
        chunk_dir.mkdir(parents=True)
        chunk_eps = [e for e in episodes if e["data/chunk_index"] == chunk_idx]
        table = _make_episode_table(chunk_eps, CAMERA_KEYS)
        pq.write_table(table, chunk_dir / "file-000.parquet")

    # data/ parquet files
    for ep in episodes:
        chunk_dir = root / "data" / f"chunk-{ep['data/chunk_index']:03d}"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        data_table = _make_data_parquet(ep["length"], ep["episode_index"])
        pq.write_table(data_table, chunk_dir / f"file-{ep['data/file_index']:03d}.parquet")

    # videos/ (create dummy mp4 files)
    for ep in episodes:
        for cam in CAMERA_KEYS:
            vid_dir = root / "videos" / cam / f"chunk-{ep['data/chunk_index']:03d}"
            vid_dir.mkdir(parents=True, exist_ok=True)
            (vid_dir / f"file-{ep['data/file_index']:03d}.mp4").write_bytes(b"FAKE_MP4")

    return root


# ---------------------------------------------------------------------------
# Tests: read utilities
# ---------------------------------------------------------------------------


class TestReadUtilities:
    def test_read_info(self, sample_dataset: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import read_info

        info = read_info(sample_dataset)
        assert info["total_episodes"] == 5
        assert info["fps"] == 30
        assert info["robot_type"] == "test_robot"

    def test_read_episodes(self, sample_dataset: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import read_episodes

        table = read_episodes(sample_dataset)
        assert len(table) == 5
        assert "episode_index" in table.schema.names
        assert table.column("episode_index").to_pylist() == [0, 1, 2, 3, 4]

    def test_read_episodes_multi_chunk(self, sample_dataset: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import read_episodes

        table = read_episodes(sample_dataset)
        chunk_indices = table.column("data/chunk_index").to_pylist()
        assert chunk_indices == [0, 0, 0, 1, 1]

    def test_read_tasks(self, sample_dataset: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import read_tasks

        table = read_tasks(sample_dataset)
        assert len(table) == 1
        assert "task_index" in table.schema.names

    def test_get_camera_keys(self, sample_dataset: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import read_info, get_camera_keys

        info = read_info(sample_dataset)
        keys = get_camera_keys(info)
        assert keys == ["observation.images.cam_top"]


# ---------------------------------------------------------------------------
# Tests: reindex
# ---------------------------------------------------------------------------

from backend.datasets.services.dataset_ops_engine import read_info, read_episodes, read_tasks


class TestReindex:
    def test_reindex_sequential(self, sample_dataset: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import reindex_episodes

        table = read_episodes(sample_dataset)
        camera_keys = ["observation.images.cam_top"]
        mask = pa.array([True, False, True, False, True])
        filtered = table.filter(mask)
        result = reindex_episodes(filtered, camera_keys, chunks_size=1000)
        assert result.column("episode_index").to_pylist() == [0, 1, 2]
        lengths = result.column("length").to_pylist()
        froms = result.column("dataset_from_index").to_pylist()
        tos = result.column("dataset_to_index").to_pylist()
        assert froms[0] == 0
        assert tos[0] == lengths[0]
        assert froms[1] == tos[0]
        assert tos[1] == froms[1] + lengths[1]
        assert froms[2] == tos[1]

    def test_reindex_chunk_and_file_indices(self, sample_dataset: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import reindex_episodes

        table = read_episodes(sample_dataset)
        camera_keys = ["observation.images.cam_top"]
        result = reindex_episodes(table, camera_keys, chunks_size=3)
        chunk_indices = result.column("data/chunk_index").to_pylist()
        file_indices = result.column("data/file_index").to_pylist()
        assert chunk_indices == [0, 0, 0, 1, 1]
        assert file_indices == [0, 1, 2, 0, 1]

    def test_reindex_video_columns(self, sample_dataset: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import reindex_episodes

        table = read_episodes(sample_dataset)
        camera_keys = ["observation.images.cam_top"]
        result = reindex_episodes(table, camera_keys, chunks_size=3)
        vid_chunks = result.column("videos/observation.images.cam_top/chunk_index").to_pylist()
        vid_files = result.column("videos/observation.images.cam_top/file_index").to_pylist()
        assert vid_chunks == [0, 0, 0, 1, 1]
        assert vid_files == [0, 1, 2, 0, 1]


# ---------------------------------------------------------------------------
# Tests: write dataset
# ---------------------------------------------------------------------------


class TestWriteDataset:
    def test_write_and_read_back(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import (
            write_dataset, read_info, read_episodes, read_tasks, get_camera_keys,
        )

        info = read_info(sample_dataset)
        episodes = read_episodes(sample_dataset)
        tasks = read_tasks(sample_dataset)

        output = tmp_path / "output_ds"
        write_dataset(
            output_dir=output,
            info=info,
            episodes=episodes,
            tasks=tasks,
            source_roots=[sample_dataset],
            original_episodes=[episodes],
        )

        assert (output / "meta" / "info.json").exists()
        assert (output / "meta" / "tasks.parquet").exists()

        new_info = read_info(output)
        new_episodes = read_episodes(output)
        assert new_info["total_episodes"] == 5
        assert len(new_episodes) == 5
        assert (output / "data" / "chunk-000" / "file-000.parquet").exists()
        assert (output / "videos" / "observation.images.cam_top" / "chunk-000" / "file-000.mp4").exists()
