# Internalize Dataset Operations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove lerobot dependency by implementing delete/split/merge operations directly with pyarrow, operating on the LeRobot v3.0 dataset format.

**Architecture:** A single new module `dataset_ops_engine.py` provides pure functions for dataset file manipulation (parquet + video + meta). The existing `dataset_ops_service.py` swaps lerobot imports for engine imports, keeping async job tracking unchanged. No API or UI changes.

**Tech Stack:** Python, pyarrow, shutil (file copy), json

**Spec:** `docs/superpowers/specs/2026-04-16-internalize-dataset-ops-design.md`

---

## Dataset Format Reference

```
dataset_root/
├── meta/
│   ├── info.json                                    # codebase_version, fps, robot_type, total_episodes, total_frames, chunks_size, features, splits, data_path, video_path
│   ├── tasks.parquet                                # task instruction (index) -> task_index (column)
│   ├── stats.json                                   # (optional, copy as-is or omit)
│   └── episodes/
│       └── chunk-{chunk_index:03d}/
│           └── file-{file_index:03d}.parquet        # episode_index, tasks, length, dataset_from_index, dataset_to_index, data/chunk_index, data/file_index, videos/*/chunk_index, videos/*/file_index, videos/*/from_timestamp, videos/*/to_timestamp, Serial_number, tags, grade, intervention, is_succeed
├── data/
│   └── chunk-{chunk_index:03d}/
│       └── file-{file_index:03d}.parquet            # observation.state, action, timestamp, frame_index, episode_index, index, task_index (one file per episode, file_index resets per chunk)
└── videos/
    └── {video_key}/
        └── chunk-{chunk_index:03d}/
            └── file-{file_index:03d}.mp4            # one video per episode per camera
```

**Chunk sizing:** `chunks_size` in info.json (default 1000). Episode N maps to `chunk_index = N // chunks_size`, `file_index = N % chunks_size`.

---

## Task 1: Engine — Read Utilities

**Files:**
- Create: `backend/datasets/services/dataset_ops_engine.py`
- Create: `tests/test_dataset_ops_engine.py`

- [ ] **Step 1: Write failing tests for read utilities**

In `tests/test_dataset_ops_engine.py`:

```python
"""Tests for dataset_ops_engine — direct parquet/video/meta manipulation."""

from __future__ import annotations

import json
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
        from backend.datasets.services.dataset_ops_engine import get_camera_keys

        info = read_info(sample_dataset)
        keys = get_camera_keys(info)
        assert keys == ["observation.images.cam_top"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -m pytest tests/test_dataset_ops_engine.py::TestReadUtilities -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.datasets.services.dataset_ops_engine'`

- [ ] **Step 3: Implement read utilities**

Create `backend/datasets/services/dataset_ops_engine.py`:

```python
"""Pure functions for LeRobot v3.0 dataset manipulation.

Operates directly on the filesystem using pyarrow. No lerobot dependency.
All functions are synchronous and take input_path -> output_path.
"""

from __future__ import annotations

import json
import logging
import shutil
from glob import glob
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Read utilities
# ---------------------------------------------------------------------------


def read_info(dataset_root: Path) -> dict:
    """Read meta/info.json and return as dict."""
    info_path = dataset_root / "meta" / "info.json"
    with info_path.open("r", encoding="utf-8") as fh:
        content = fh.read().rstrip("\x00")
        return json.loads(content)


def read_episodes(dataset_root: Path) -> pa.Table:
    """Read all meta/episodes/chunk-*/file-*.parquet into a single Table, sorted by episode_index."""
    pattern = str(dataset_root / "meta" / "episodes" / "chunk-*" / "file-*.parquet")
    files = sorted(glob(pattern))
    if not files:
        return pa.table({"episode_index": pa.array([], type=pa.int64())})
    tables = [pq.read_table(f) for f in files]
    combined = pa.concat_tables(tables, promote_options="default")
    indices = combined.column("episode_index").to_pylist()
    sort_order = sorted(range(len(indices)), key=lambda i: indices[i])
    return combined.take(sort_order)


def read_tasks(dataset_root: Path) -> pa.Table:
    """Read meta/tasks.parquet."""
    tasks_path = dataset_root / "meta" / "tasks.parquet"
    if not tasks_path.exists():
        return pa.table({"task_index": pa.array([], type=pa.int64())})
    return pq.read_table(str(tasks_path))


def get_camera_keys(info: dict) -> list[str]:
    """Extract camera keys from info features dict."""
    features = info.get("features", {})
    return [
        key for key in features
        if key.startswith("observation.images.") or key.startswith("observation.image.")
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -m pytest tests/test_dataset_ops_engine.py::TestReadUtilities -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/services/dataset_ops_engine.py tests/test_dataset_ops_engine.py
git commit -m "feat: add dataset_ops_engine read utilities (read_info, read_episodes, read_tasks, get_camera_keys)"
```

---

## Task 2: Engine — Reindex and Write Utilities

**Files:**
- Modify: `backend/datasets/services/dataset_ops_engine.py`
- Modify: `tests/test_dataset_ops_engine.py`

- [ ] **Step 1: Write failing tests for reindex and write**

Append to `tests/test_dataset_ops_engine.py`:

```python
from backend.datasets.services.dataset_ops_engine import read_info, read_episodes, read_tasks


class TestReindex:
    def test_reindex_sequential(self, sample_dataset: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import reindex_episodes

        table = read_episodes(sample_dataset)
        info = read_info(sample_dataset)
        camera_keys = ["observation.images.cam_top"]
        # Remove episode 1 and 3
        mask = pa.array([True, False, True, False, True])
        filtered = table.filter(mask)
        result = reindex_episodes(filtered, camera_keys, chunks_size=1000)
        assert result.column("episode_index").to_pylist() == [0, 1, 2]
        # dataset_from/to should be recalculated
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


class TestWriteDataset:
    def test_write_and_read_back(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import (
            write_dataset, read_info, read_episodes, read_tasks, get_camera_keys, reindex_episodes,
        )

        info = read_info(sample_dataset)
        episodes = read_episodes(sample_dataset)
        tasks = read_tasks(sample_dataset)
        camera_keys = get_camera_keys(info)

        output = tmp_path / "output_ds"
        write_dataset(
            output_dir=output,
            info=info,
            episodes=episodes,
            tasks=tasks,
            source_roots=[sample_dataset],
            original_episodes=[episodes],
        )

        # Verify structure
        assert (output / "meta" / "info.json").exists()
        assert (output / "meta" / "tasks.parquet").exists()

        # Read back
        new_info = read_info(output)
        new_episodes = read_episodes(output)
        assert new_info["total_episodes"] == 5
        assert len(new_episodes) == 5

        # Verify data parquets copied
        assert (output / "data" / "chunk-000" / "file-000.parquet").exists()

        # Verify videos copied
        assert (output / "videos" / "observation.images.cam_top" / "chunk-000" / "file-000.mp4").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dataset_ops_engine.py::TestReindex tests/test_dataset_ops_engine.py::TestWriteDataset -v`
Expected: FAIL — `ImportError: cannot import name 'reindex_episodes'`

- [ ] **Step 3: Implement reindex_episodes**

Append to `backend/datasets/services/dataset_ops_engine.py`:

```python
# ---------------------------------------------------------------------------
# Reindex
# ---------------------------------------------------------------------------


def reindex_episodes(
    episodes: pa.Table,
    camera_keys: list[str],
    chunks_size: int = 1000,
) -> pa.Table:
    """Reassign episode_index 0..N-1 and recompute derived columns.

    Updates: episode_index, dataset_from_index, dataset_to_index,
    data/chunk_index, data/file_index, videos/*/chunk_index, videos/*/file_index.
    Preserves all other columns as-is.
    """
    n = len(episodes)
    if n == 0:
        return episodes

    lengths = episodes.column("length").to_pylist()

    new_episode_index = list(range(n))
    new_chunk_index = [i // chunks_size for i in range(n)]
    new_file_index = [i % chunks_size for i in range(n)]

    # Cumulative from/to
    new_from = []
    new_to = []
    offset = 0
    for length in lengths:
        new_from.append(offset)
        new_to.append(offset + length)
        offset += length

    # Build replacement columns
    replacements = {
        "episode_index": pa.array(new_episode_index, type=pa.int64()),
        "dataset_from_index": pa.array(new_from, type=pa.int64()),
        "dataset_to_index": pa.array(new_to, type=pa.int64()),
        "data/chunk_index": pa.array(new_chunk_index, type=pa.int64()),
        "data/file_index": pa.array(new_file_index, type=pa.int64()),
    }

    for cam in camera_keys:
        chunk_col = f"videos/{cam}/chunk_index"
        file_col = f"videos/{cam}/file_index"
        if chunk_col in episodes.schema.names:
            replacements[chunk_col] = pa.array(new_chunk_index, type=pa.int64())
        if file_col in episodes.schema.names:
            replacements[file_col] = pa.array(new_file_index, type=pa.int64())

    # Apply replacements
    result = episodes
    for col_name, col_array in replacements.items():
        idx = result.schema.get_field_index(col_name)
        if idx >= 0:
            result = result.set_column(idx, col_name, col_array)

    return result
```

- [ ] **Step 4: Implement write_dataset**

Append to `backend/datasets/services/dataset_ops_engine.py`:

```python
# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_dataset(
    output_dir: Path,
    info: dict,
    episodes: pa.Table,
    tasks: pa.Table,
    source_roots: list[Path],
    original_episodes: list[pa.Table],
) -> None:
    """Write a complete dataset to output_dir.

    Copies data parquets and video files from source_roots based on
    original_episodes (pre-reindex tables), mapping old positions to new
    positions in the reindexed episodes table.

    Args:
        output_dir: Target directory (will be created).
        info: info.json dict (total_episodes/total_frames will be updated).
        episodes: Reindexed episodes table to write.
        tasks: Tasks table to write.
        source_roots: List of source dataset root paths (one per original_episodes entry).
        original_episodes: List of episode tables before reindex, aligned with source_roots.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    camera_keys = get_camera_keys(info)
    chunks_size = info.get("chunks_size", 1000)
    data_path_tmpl = info.get("data_path", "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet")
    video_path_tmpl = info.get("video_path", "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4")

    new_ep_list = _table_to_dicts(episodes)

    # Build mapping: new_episode_index -> (source_root, old_chunk_index, old_file_index)
    source_map: list[tuple[Path, int, int]] = []
    for src_root, orig_table in zip(source_roots, original_episodes):
        for row_idx in range(len(orig_table)):
            old_chunk = orig_table.column("data/chunk_index")[row_idx].as_py()
            old_file = orig_table.column("data/file_index")[row_idx].as_py()
            source_map.append((src_root, old_chunk, old_file))

    # Write data parquets and videos
    for new_idx, (src_root, old_chunk, old_file) in enumerate(source_map):
        new_ep = new_ep_list[new_idx]
        new_chunk = new_ep["data/chunk_index"]
        new_file = new_ep["data/file_index"]

        # Copy data parquet
        old_data = src_root / data_path_tmpl.format(chunk_index=old_chunk, file_index=old_file)
        new_data = output_dir / data_path_tmpl.format(chunk_index=new_chunk, file_index=new_file)
        new_data.parent.mkdir(parents=True, exist_ok=True)
        if old_data.exists():
            # Rewrite episode_index and index columns in the data parquet
            data_table = pq.read_table(str(old_data))
            if "episode_index" in data_table.schema.names:
                num_rows = len(data_table)
                col_idx = data_table.schema.get_field_index("episode_index")
                data_table = data_table.set_column(
                    col_idx, "episode_index",
                    pa.array([new_idx] * num_rows, type=pa.int64()),
                )
            pq.write_table(data_table, str(new_data))

        # Copy videos
        for cam in camera_keys:
            old_video = src_root / video_path_tmpl.format(video_key=cam, chunk_index=old_chunk, file_index=old_file)
            new_video = output_dir / video_path_tmpl.format(video_key=cam, chunk_index=new_chunk, file_index=new_file)
            new_video.parent.mkdir(parents=True, exist_ok=True)
            if old_video.exists():
                shutil.copy2(str(old_video), str(new_video))

    # Write episodes parquet (single chunk)
    ep_dir = output_dir / "meta" / "episodes" / "chunk-000"
    ep_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(episodes, str(ep_dir / "file-000.parquet"))

    # Write tasks parquet
    meta_dir = output_dir / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(tasks, str(meta_dir / "tasks.parquet"))

    # Write info.json with updated totals
    total_frames = sum(episodes.column("length").to_pylist()) if len(episodes) > 0 else 0
    updated_info = {**info}
    updated_info["total_episodes"] = len(episodes)
    updated_info["total_frames"] = total_frames
    updated_info["splits"] = {"train": f"0:{len(episodes)}"}
    with (meta_dir / "info.json").open("w", encoding="utf-8") as fh:
        json.dump(updated_info, fh, indent=2)


def _table_to_dicts(table: pa.Table) -> list[dict]:
    """Convert a pyarrow Table to a list of dicts."""
    names = table.schema.names
    columns = [table.column(n).to_pylist() for n in names]
    return [dict(zip(names, row)) for row in zip(*columns)]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_dataset_ops_engine.py::TestReindex tests/test_dataset_ops_engine.py::TestWriteDataset -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/datasets/services/dataset_ops_engine.py tests/test_dataset_ops_engine.py
git commit -m "feat: add reindex_episodes and write_dataset to dataset_ops_engine"
```

---

## Task 3: Engine — delete_episodes

**Files:**
- Modify: `backend/datasets/services/dataset_ops_engine.py`
- Modify: `tests/test_dataset_ops_engine.py`

- [ ] **Step 1: Write failing tests for delete_episodes**

Append to `tests/test_dataset_ops_engine.py`:

```python
class TestDeleteEpisodes:
    def test_delete_middle_episodes(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import delete_episodes, read_info, read_episodes

        output = tmp_path / "after_delete"
        delete_episodes(sample_dataset, episode_ids=[1, 3], output_dir=output)

        info = read_info(output)
        assert info["total_episodes"] == 3

        episodes = read_episodes(output)
        assert episodes.column("episode_index").to_pylist() == [0, 1, 2]

        # Original episodes 0, 2, 4 remain (serial numbers preserved)
        serials = episodes.column("Serial_number").to_pylist()
        assert serials == ["SN_000000", "SN_000002", "SN_000004"]

        # dataset_from/to recalculated
        froms = episodes.column("dataset_from_index").to_pylist()
        lengths = episodes.column("length").to_pylist()
        assert froms[0] == 0
        assert froms[1] == lengths[0]
        assert froms[2] == lengths[0] + lengths[1]

    def test_delete_preserves_data_parquets(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import delete_episodes

        output = tmp_path / "after_delete"
        delete_episodes(sample_dataset, episode_ids=[1, 3], output_dir=output)

        # 3 data parquets should exist (chunk-000 only since 3 < chunks_size default 1000)
        data_files = sorted((output / "data" / "chunk-000").glob("*.parquet"))
        assert len(data_files) == 3

        # Verify episode_index rewritten in data parquet
        import pyarrow.parquet as pq
        t = pq.read_table(str(data_files[1]))
        assert t.column("episode_index")[0].as_py() == 1

    def test_delete_preserves_videos(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import delete_episodes

        output = tmp_path / "after_delete"
        delete_episodes(sample_dataset, episode_ids=[1, 3], output_dir=output)

        vid_dir = output / "videos" / "observation.images.cam_top" / "chunk-000"
        vids = sorted(vid_dir.glob("*.mp4"))
        assert len(vids) == 3

    def test_delete_from_multi_chunk(self, sample_dataset: Path, tmp_path: Path) -> None:
        """Delete episode 4 (in chunk-001 of source). Result should be single chunk."""
        from backend.datasets.services.dataset_ops_engine import delete_episodes, read_episodes

        output = tmp_path / "after_delete"
        delete_episodes(sample_dataset, episode_ids=[4], output_dir=output)

        episodes = read_episodes(output)
        assert len(episodes) == 4
        # All in chunk-000 now (4 < default chunks_size 1000)
        assert all(c == 0 for c in episodes.column("data/chunk_index").to_pylist())

    def test_delete_empty_list(self, sample_dataset: Path, tmp_path: Path) -> None:
        """Delete nothing — output should be identical to input."""
        from backend.datasets.services.dataset_ops_engine import delete_episodes, read_episodes

        output = tmp_path / "no_delete"
        delete_episodes(sample_dataset, episode_ids=[], output_dir=output)

        episodes = read_episodes(output)
        assert len(episodes) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dataset_ops_engine.py::TestDeleteEpisodes -v`
Expected: FAIL — `ImportError: cannot import name 'delete_episodes'`

- [ ] **Step 3: Implement delete_episodes**

Append to `backend/datasets/services/dataset_ops_engine.py`:

```python
# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def delete_episodes(
    dataset_root: Path,
    episode_ids: list[int],
    output_dir: Path,
) -> Path:
    """Delete specified episodes and write result to output_dir.

    Remaining episodes are reindexed from 0. Data parquets and videos
    for kept episodes are copied with updated indices.

    Returns output_dir.
    """
    info = read_info(dataset_root)
    episodes = read_episodes(dataset_root)
    tasks = read_tasks(dataset_root)
    camera_keys = get_camera_keys(info)
    chunks_size = info.get("chunks_size", 1000)

    # Filter: keep episodes NOT in episode_ids
    delete_set = set(episode_ids)
    mask = pa.array([
        idx not in delete_set
        for idx in episodes.column("episode_index").to_pylist()
    ])
    kept = episodes.filter(mask)
    original_kept = kept  # before reindex, for source mapping

    # Reindex
    reindexed = reindex_episodes(kept, camera_keys, chunks_size)

    # Write
    write_dataset(
        output_dir=output_dir,
        info=info,
        episodes=reindexed,
        tasks=tasks,
        source_roots=[dataset_root],
        original_episodes=[original_kept],
    )

    logger.info("Deleted %d episodes from %s -> %s", len(episode_ids), dataset_root, output_dir)
    return output_dir
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dataset_ops_engine.py::TestDeleteEpisodes -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/services/dataset_ops_engine.py tests/test_dataset_ops_engine.py
git commit -m "feat: add delete_episodes to dataset_ops_engine"
```

---

## Task 4: Engine — split_dataset

**Files:**
- Modify: `backend/datasets/services/dataset_ops_engine.py`
- Modify: `tests/test_dataset_ops_engine.py`

- [ ] **Step 1: Write failing tests for split_dataset**

Append to `tests/test_dataset_ops_engine.py`:

```python
class TestSplitDataset:
    def test_split_selected_episodes(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import split_dataset, read_info, read_episodes

        output = tmp_path / "split_out"
        split_dataset(sample_dataset, episode_ids=[1, 3], output_dir=output)

        info = read_info(output)
        assert info["total_episodes"] == 2

        episodes = read_episodes(output)
        assert episodes.column("episode_index").to_pylist() == [0, 1]
        # Original serial numbers preserved
        serials = episodes.column("Serial_number").to_pylist()
        assert serials == ["SN_000001", "SN_000003"]

    def test_split_preserves_data(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import split_dataset

        output = tmp_path / "split_out"
        split_dataset(sample_dataset, episode_ids=[2, 4], output_dir=output)

        data_files = sorted((output / "data" / "chunk-000").glob("*.parquet"))
        assert len(data_files) == 2

    def test_split_preserves_videos(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import split_dataset

        output = tmp_path / "split_out"
        split_dataset(sample_dataset, episode_ids=[0], output_dir=output)

        vid = output / "videos" / "observation.images.cam_top" / "chunk-000" / "file-000.mp4"
        assert vid.exists()

    def test_split_single_episode(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import split_dataset, read_episodes

        output = tmp_path / "split_one"
        split_dataset(sample_dataset, episode_ids=[4], output_dir=output)

        episodes = read_episodes(output)
        assert len(episodes) == 1
        assert episodes.column("episode_index").to_pylist() == [0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dataset_ops_engine.py::TestSplitDataset -v`
Expected: FAIL — `ImportError: cannot import name 'split_dataset'`

- [ ] **Step 3: Implement split_dataset**

Append to `backend/datasets/services/dataset_ops_engine.py`:

```python
def split_dataset(
    dataset_root: Path,
    episode_ids: list[int],
    output_dir: Path,
) -> Path:
    """Extract specified episodes into a new dataset at output_dir.

    Selected episodes are reindexed from 0. Data parquets and videos
    are copied with updated indices.

    Returns output_dir.
    """
    info = read_info(dataset_root)
    episodes = read_episodes(dataset_root)
    tasks = read_tasks(dataset_root)
    camera_keys = get_camera_keys(info)
    chunks_size = info.get("chunks_size", 1000)

    # Filter: keep ONLY episodes in episode_ids
    select_set = set(episode_ids)
    mask = pa.array([
        idx in select_set
        for idx in episodes.column("episode_index").to_pylist()
    ])
    selected = episodes.filter(mask)
    original_selected = selected  # before reindex

    # Reindex
    reindexed = reindex_episodes(selected, camera_keys, chunks_size)

    # Write
    write_dataset(
        output_dir=output_dir,
        info=info,
        episodes=reindexed,
        tasks=tasks,
        source_roots=[dataset_root],
        original_episodes=[original_selected],
    )

    logger.info("Split %d episodes from %s -> %s", len(episode_ids), dataset_root, output_dir)
    return output_dir
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dataset_ops_engine.py::TestSplitDataset -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/services/dataset_ops_engine.py tests/test_dataset_ops_engine.py
git commit -m "feat: add split_dataset to dataset_ops_engine"
```

---

## Task 5: Engine — merge_datasets

**Files:**
- Modify: `backend/datasets/services/dataset_ops_engine.py`
- Modify: `tests/test_dataset_ops_engine.py`

- [ ] **Step 1: Write failing tests for merge_datasets**

Append to `tests/test_dataset_ops_engine.py`:

```python
class TestMergeDatasets:
    def test_merge_two_datasets(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import (
            split_dataset, merge_datasets, read_info, read_episodes,
        )

        # Create two datasets by splitting
        ds_a = tmp_path / "ds_a"
        ds_b = tmp_path / "ds_b"
        split_dataset(sample_dataset, episode_ids=[0, 1], output_dir=ds_a)
        split_dataset(sample_dataset, episode_ids=[2, 3, 4], output_dir=ds_b)

        # Merge them
        merged = tmp_path / "merged"
        merge_datasets([ds_a, ds_b], output_dir=merged)

        info = read_info(merged)
        assert info["total_episodes"] == 5

        episodes = read_episodes(merged)
        assert episodes.column("episode_index").to_pylist() == [0, 1, 2, 3, 4]

        # dataset_from/to should be continuous
        froms = episodes.column("dataset_from_index").to_pylist()
        tos = episodes.column("dataset_to_index").to_pylist()
        for i in range(1, len(froms)):
            assert froms[i] == tos[i - 1]

    def test_merge_preserves_all_data(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import split_dataset, merge_datasets

        ds_a = tmp_path / "ds_a"
        ds_b = tmp_path / "ds_b"
        split_dataset(sample_dataset, episode_ids=[0, 1], output_dir=ds_a)
        split_dataset(sample_dataset, episode_ids=[2], output_dir=ds_b)

        merged = tmp_path / "merged"
        merge_datasets([ds_a, ds_b], output_dir=merged)

        data_files = sorted((merged / "data" / "chunk-000").glob("*.parquet"))
        assert len(data_files) == 3

        vid_files = sorted((merged / "videos" / "observation.images.cam_top" / "chunk-000").glob("*.mp4"))
        assert len(vid_files) == 3

    def test_merge_validates_fps(self, sample_dataset: Path, tmp_path: Path) -> None:
        """Merge should fail if fps doesn't match."""
        from backend.datasets.services.dataset_ops_engine import split_dataset, merge_datasets, read_info

        ds_a = tmp_path / "ds_a"
        ds_b = tmp_path / "ds_b"
        split_dataset(sample_dataset, episode_ids=[0], output_dir=ds_a)
        split_dataset(sample_dataset, episode_ids=[1], output_dir=ds_b)

        # Tamper with ds_b's fps
        info_b = read_info(ds_b)
        info_b["fps"] = 60
        (ds_b / "meta" / "info.json").write_text(json.dumps(info_b))

        with pytest.raises(ValueError, match="fps"):
            merge_datasets([ds_a, ds_b], output_dir=tmp_path / "bad_merge")

    def test_merge_validates_robot_type(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_engine import split_dataset, merge_datasets, read_info

        ds_a = tmp_path / "ds_a"
        ds_b = tmp_path / "ds_b"
        split_dataset(sample_dataset, episode_ids=[0], output_dir=ds_a)
        split_dataset(sample_dataset, episode_ids=[1], output_dir=ds_b)

        info_b = read_info(ds_b)
        info_b["robot_type"] = "other_robot"
        (ds_b / "meta" / "info.json").write_text(json.dumps(info_b))

        with pytest.raises(ValueError, match="robot_type"):
            merge_datasets([ds_a, ds_b], output_dir=tmp_path / "bad_merge")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dataset_ops_engine.py::TestMergeDatasets -v`
Expected: FAIL — `ImportError: cannot import name 'merge_datasets'`

- [ ] **Step 3: Implement merge_datasets**

Append to `backend/datasets/services/dataset_ops_engine.py`:

```python
def merge_datasets(
    dataset_roots: list[Path],
    output_dir: Path,
) -> Path:
    """Merge multiple datasets into one at output_dir.

    Validates fps and robot_type compatibility. Concatenates episodes
    and reindexes from 0. All data parquets and videos are copied.

    Returns output_dir.
    """
    if not dataset_roots:
        raise ValueError("No datasets to merge")

    infos = [read_info(r) for r in dataset_roots]
    all_episodes = [read_episodes(r) for r in dataset_roots]
    all_tasks = [read_tasks(r) for r in dataset_roots]

    # Validate compatibility
    base_fps = infos[0].get("fps")
    base_robot = infos[0].get("robot_type")
    for i, info in enumerate(infos[1:], 1):
        if info.get("fps") != base_fps:
            raise ValueError(
                f"fps mismatch: dataset 0 has fps={base_fps}, "
                f"dataset {i} has fps={info.get('fps')}"
            )
        if info.get("robot_type") != base_robot:
            raise ValueError(
                f"robot_type mismatch: dataset 0 has robot_type={base_robot!r}, "
                f"dataset {i} has robot_type={info.get('robot_type')!r}"
            )

    # Concatenate episodes
    combined = pa.concat_tables(all_episodes, promote_options="default")

    # Concatenate and deduplicate tasks
    combined_tasks = pa.concat_tables(all_tasks, promote_options="default")
    # Simple dedup: keep unique task_index values
    seen: set[int] = set()
    keep_mask = []
    for idx in combined_tasks.column("task_index").to_pylist():
        if idx not in seen:
            seen.add(idx)
            keep_mask.append(True)
        else:
            keep_mask.append(False)
    deduped_tasks = combined_tasks.filter(pa.array(keep_mask))

    # Reindex
    camera_keys = get_camera_keys(infos[0])
    chunks_size = infos[0].get("chunks_size", 1000)
    reindexed = reindex_episodes(combined, camera_keys, chunks_size)

    # Write
    write_dataset(
        output_dir=output_dir,
        info=infos[0],
        episodes=reindexed,
        tasks=deduped_tasks,
        source_roots=dataset_roots,
        original_episodes=all_episodes,
    )

    logger.info(
        "Merged %d datasets (%d total episodes) -> %s",
        len(dataset_roots), len(reindexed), output_dir,
    )
    return output_dir
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dataset_ops_engine.py::TestMergeDatasets -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/services/dataset_ops_engine.py tests/test_dataset_ops_engine.py
git commit -m "feat: add merge_datasets to dataset_ops_engine with validation"
```

---

## Task 6: Replace lerobot in dataset_ops_service.py

**Files:**
- Modify: `backend/datasets/services/dataset_ops_service.py`

- [ ] **Step 1: Write failing test for the new service behavior**

Append to `tests/test_dataset_ops_engine.py`:

```python
class TestServiceIntegration:
    """Test that DatasetOpsService correctly delegates to the engine."""

    @pytest.mark.asyncio
    async def test_delete_via_service(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_service import DatasetOpsService
        from backend.datasets.services.dataset_ops_engine import read_info, read_episodes
        import asyncio

        svc = DatasetOpsService()
        output = tmp_path / "svc_delete"
        job_id = await svc.delete_episodes(sample_dataset, [1, 3], output_dir=output)
        await asyncio.sleep(1.0)

        job = svc.get_job_status(job_id)
        assert job["status"] == "complete"
        assert job["error"] is None

        info = read_info(output)
        assert info["total_episodes"] == 3

    @pytest.mark.asyncio
    async def test_split_via_service(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_service import DatasetOpsService
        from backend.datasets.services.dataset_ops_engine import read_info
        import asyncio

        svc = DatasetOpsService()
        output = tmp_path / "svc_split"
        job_id = await svc.split_dataset(sample_dataset, [0, 2], "svc_split", output_dir=output)
        await asyncio.sleep(1.0)

        job = svc.get_job_status(job_id)
        assert job["status"] == "complete"
        assert read_info(output)["total_episodes"] == 2

    @pytest.mark.asyncio
    async def test_merge_via_service(self, sample_dataset: Path, tmp_path: Path) -> None:
        from backend.datasets.services.dataset_ops_service import DatasetOpsService
        from backend.datasets.services.dataset_ops_engine import split_dataset, read_info
        import asyncio

        ds_a = tmp_path / "a"
        ds_b = tmp_path / "b"
        split_dataset(sample_dataset, [0, 1], ds_a)
        split_dataset(sample_dataset, [2, 3], ds_b)

        svc = DatasetOpsService()
        output = tmp_path / "svc_merge"
        job_id = await svc.merge_datasets([ds_a, ds_b], "svc_merge", output_dir=output)
        await asyncio.sleep(1.0)

        job = svc.get_job_status(job_id)
        assert job["status"] == "complete"
        assert read_info(output)["total_episodes"] == 4

    @pytest.mark.asyncio
    async def test_delete_inplace_backup_restore(self, sample_dataset: Path, tmp_path: Path) -> None:
        """In-place delete should use backup/restore pattern."""
        from backend.datasets.services.dataset_ops_engine import read_info, read_episodes
        from backend.datasets.services.dataset_ops_service import DatasetOpsService
        import asyncio

        # Copy sample to a writable location for in-place test
        work = tmp_path / "inplace_ds"
        shutil.copytree(str(sample_dataset), str(work))

        svc = DatasetOpsService()
        job_id = await svc.delete_episodes(work, [0, 4])
        await asyncio.sleep(1.0)

        job = svc.get_job_status(job_id)
        assert job["status"] == "complete"
        assert job["result_path"] == str(work)

        info = read_info(work)
        assert info["total_episodes"] == 3

        # No .bak left behind
        assert not work.with_suffix(".bak").exists()
```

Add import at top of test file:

```python
import shutil
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dataset_ops_engine.py::TestServiceIntegration -v`
Expected: FAIL — service still imports lerobot

- [ ] **Step 3: Rewrite dataset_ops_service.py**

Replace the entire content of `backend/datasets/services/dataset_ops_service.py`:

```python
"""Service for dataset split/merge/delete operations.

Wraps dataset_ops_engine with async job tracking. All blocking operations
run in a thread executor to avoid blocking the async event loop.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.datasets.services import dataset_ops_engine as engine

logger = logging.getLogger(__name__)


class DatasetOpsService:
    """Manages dataset split/merge/delete operations with async job tracking."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Job tracking
    # ------------------------------------------------------------------

    def _create_job(self, operation: str) -> dict[str, Any]:
        job: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "operation": operation,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "error": None,
            "result_path": None,
        }
        self._jobs[job["id"]] = job
        return job

    def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def delete_episodes(
        self,
        source_path: str | Path,
        episode_ids: list[int],
        output_dir: str | Path | None = None,
    ) -> str:
        """Queue a delete-episodes job. Returns the job ID."""
        job = self._create_job("delete")
        job_id = job["id"]

        source = Path(source_path)
        out_dir = Path(output_dir) if output_dir else None

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, self._run_delete, job_id, source, episode_ids, out_dir)
        return job_id

    async def split_dataset(
        self,
        source_path: str | Path,
        episode_ids: list[int],
        target_name: str,
        output_dir: str | Path | None = None,
    ) -> str:
        """Queue a split job. Returns the job ID."""
        job = self._create_job("split")
        job_id = job["id"]

        source = Path(source_path)
        out_dir = Path(output_dir) if output_dir else source.parent / target_name

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, self._run_split, job_id, source, episode_ids, out_dir)
        return job_id

    async def split_and_merge(
        self,
        source_path: str | Path,
        episode_ids: list[int],
        target_path: str | Path,
        target_name: str,
    ) -> str:
        """Queue a split-into-existing job. Returns the job ID."""
        job = self._create_job("split_and_merge")
        job_id = job["id"]

        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None, self._run_split_and_merge,
            job_id, Path(source_path), episode_ids, Path(target_path), target_name,
        )
        return job_id

    async def merge_datasets(
        self,
        source_paths: list[str | Path],
        target_name: str,
        output_dir: str | Path | None = None,
    ) -> str:
        """Queue a merge job. Returns the job ID."""
        job = self._create_job("merge")
        job_id = job["id"]

        sources = [Path(p) for p in source_paths]
        out_dir = Path(output_dir) if output_dir else sources[0].parent / target_name

        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, self._run_merge, job_id, sources, out_dir)
        return job_id

    # ------------------------------------------------------------------
    # Blocking workers (run in thread executor)
    # ------------------------------------------------------------------

    def _run_with_backup(
        self,
        job_id: str,
        target_path: Path,
        fn: callable,
    ) -> None:
        """Run fn() with backup/restore for in-place operations.

        fn receives (backup_path, target_path) and should write result to target_path.
        """
        backup = target_path.with_suffix(target_path.suffix + ".bak")
        target_path.rename(backup)
        try:
            fn(backup, target_path)
            shutil.rmtree(backup)
        except Exception:
            if target_path.exists():
                shutil.rmtree(target_path)
            backup.rename(target_path)
            raise

    def _run_delete(
        self,
        job_id: str,
        source_path: Path,
        episode_ids: list[int],
        output_dir: Path | None,
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = "running"

        try:
            in_place = output_dir is None
            if in_place:
                self._run_with_backup(
                    job_id, source_path,
                    lambda src, dst: engine.delete_episodes(src, episode_ids, dst),
                )
                result_path = source_path
            else:
                engine.delete_episodes(source_path, episode_ids, output_dir)
                result_path = output_dir

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(result_path)
            logger.info("Delete job %s complete: %s", job_id, result_path)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Delete job %s failed", job_id)

    def _run_split(
        self,
        job_id: str,
        source_path: Path,
        episode_ids: list[int],
        output_path: Path,
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = "running"

        try:
            engine.split_dataset(source_path, episode_ids, output_path)

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(output_path)
            logger.info("Split job %s complete: %s", job_id, output_path)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Split job %s failed", job_id)

    def _run_merge(
        self,
        job_id: str,
        source_paths: list[Path],
        output_path: Path,
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = "running"

        try:
            engine.merge_datasets(source_paths, output_path)

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(output_path)
            logger.info("Merge job %s complete: %s", job_id, output_path)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Merge job %s failed", job_id)

    def _run_split_and_merge(
        self,
        job_id: str,
        source_path: Path,
        episode_ids: list[int],
        target_path: Path,
        target_name: str,
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = "running"
        split_tmp: Path | None = None

        try:
            import tempfile

            # Step 1: Split selected episodes to temp
            split_tmp = Path(tempfile.mkdtemp(prefix="split-tmp-"))
            engine.split_dataset(source_path, episode_ids, split_tmp)

            # Step 2: Merge split result into target (in-place with backup)
            self._run_with_backup(
                job_id, target_path,
                lambda src, dst: engine.merge_datasets([src, split_tmp], dst),
            )

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(target_path)
            logger.info("Split-and-merge job %s complete: %s", job_id, target_path)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Split-and-merge job %s failed", job_id)

        finally:
            if split_tmp is not None and split_tmp.exists():
                shutil.rmtree(split_tmp, ignore_errors=True)


dataset_ops_service = DatasetOpsService()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dataset_ops_engine.py::TestServiceIntegration -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/services/dataset_ops_service.py tests/test_dataset_ops_engine.py
git commit -m "refactor: replace lerobot imports with dataset_ops_engine in service layer"
```

---

## Task 7: Update existing tests and cleanup

**Files:**
- Modify: `tests/test_dataset_ops_service.py`

- [ ] **Step 1: Rewrite test_dataset_ops_service.py**

Replace the entire content of `tests/test_dataset_ops_service.py`:

```python
"""Tests for DatasetOpsService — job tracking and async API."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.datasets.services.dataset_ops_service import DatasetOpsService


@pytest.fixture()
def service() -> DatasetOpsService:
    return DatasetOpsService()


class TestJobTracking:
    def test_get_job_status_unknown(self, service: DatasetOpsService) -> None:
        assert service.get_job_status("nonexistent") is None

    def test_create_job_fields(self, service: DatasetOpsService) -> None:
        job = service._create_job("split")
        assert job["operation"] == "split"
        assert job["status"] == "queued"
        assert job["completed_at"] is None
        assert job["error"] is None
        assert job["result_path"] is None
        assert service.get_job_status(job["id"]) is job


class TestPublicAPI:
    @pytest.mark.asyncio
    async def test_delete_returns_job_id(self, service: DatasetOpsService) -> None:
        with patch.object(service, "_run_delete"):
            job_id = await service.delete_episodes("/tmp/ds", [0, 1])
            assert isinstance(job_id, str)
            assert len(job_id) == 36

    @pytest.mark.asyncio
    async def test_split_returns_job_id(self, service: DatasetOpsService) -> None:
        with patch.object(service, "_run_split"):
            job_id = await service.split_dataset("/tmp/ds", [0], "split-out")
            assert isinstance(job_id, str)

    @pytest.mark.asyncio
    async def test_merge_returns_job_id(self, service: DatasetOpsService) -> None:
        with patch.object(service, "_run_merge"):
            job_id = await service.merge_datasets(["/tmp/a", "/tmp/b"], "merged")
            assert isinstance(job_id, str)

    @pytest.mark.asyncio
    async def test_split_and_merge_returns_job_id(self, service: DatasetOpsService) -> None:
        with patch.object(service, "_run_split_and_merge"):
            job_id = await service.split_and_merge("/tmp/src", [0], "/tmp/tgt", "tgt")
            assert isinstance(job_id, str)


def test_singleton_import() -> None:
    from backend.datasets.services.dataset_ops_service import dataset_ops_service
    assert isinstance(dataset_ops_service, DatasetOpsService)
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/test_dataset_ops_service.py tests/test_dataset_ops_engine.py -v`
Expected: All tests PASS

- [ ] **Step 3: Verify no lerobot references remain**

Run: `grep -r "lerobot" backend/ tests/ --include="*.py"`
Expected: No output (zero matches)

- [ ] **Step 4: Commit**

```bash
git add tests/test_dataset_ops_service.py
git commit -m "refactor: remove lerobot mocks from service tests, simplify to job tracking tests"
```

---

## Task 8: Final Verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Verify no lerobot references in entire codebase**

Run: `grep -r "lerobot" backend/ tests/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx"`
Expected: No references to lerobot imports or function calls

- [ ] **Step 3: Verify backend starts**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -c "from backend.datasets.services.dataset_ops_service import dataset_ops_service; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit all and tag**

```bash
git add -A
git status
# Verify only expected files changed
git commit -m "feat: internalize dataset delete/split/merge, remove lerobot dependency"
```
