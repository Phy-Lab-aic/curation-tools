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


# ---------------------------------------------------------------------------
# Reindex
# ---------------------------------------------------------------------------


def reindex_episodes(
    episodes: pa.Table,
    camera_keys: list[str],
    chunks_size: int = 1000,
) -> pa.Table:
    """Reassign episode_index 0..N-1 and recompute derived columns."""
    n = len(episodes)
    if n == 0:
        return episodes

    lengths = episodes.column("length").to_pylist()

    new_episode_index = list(range(n))
    new_chunk_index = [i // chunks_size for i in range(n)]
    new_file_index = [i % chunks_size for i in range(n)]

    new_from = []
    new_to = []
    offset = 0
    for length in lengths:
        new_from.append(offset)
        new_to.append(offset + length)
        offset += length

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

    result = episodes
    for col_name, col_array in replacements.items():
        idx = result.schema.get_field_index(col_name)
        if idx >= 0:
            result = result.set_column(idx, col_name, col_array)

    return result


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
    """Write a complete dataset to output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    camera_keys = get_camera_keys(info)
    data_path_tmpl = info.get("data_path", "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet")
    video_path_tmpl = info.get("video_path", "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4")

    new_ep_list = _table_to_dicts(episodes)

    source_map: list[tuple[Path, int, int]] = []
    for src_root, orig_table in zip(source_roots, original_episodes):
        for row_idx in range(len(orig_table)):
            old_chunk = orig_table.column("data/chunk_index")[row_idx].as_py()
            old_file = orig_table.column("data/file_index")[row_idx].as_py()
            source_map.append((src_root, old_chunk, old_file))

    for new_idx, (src_root, old_chunk, old_file) in enumerate(source_map):
        new_ep = new_ep_list[new_idx]
        new_chunk = new_ep["data/chunk_index"]
        new_file = new_ep["data/file_index"]

        old_data = src_root / data_path_tmpl.format(chunk_index=old_chunk, file_index=old_file)
        new_data = output_dir / data_path_tmpl.format(chunk_index=new_chunk, file_index=new_file)
        new_data.parent.mkdir(parents=True, exist_ok=True)
        if old_data.exists():
            data_table = pq.read_table(str(old_data))
            if "episode_index" in data_table.schema.names:
                num_rows = len(data_table)
                col_idx = data_table.schema.get_field_index("episode_index")
                data_table = data_table.set_column(
                    col_idx, "episode_index",
                    pa.array([new_idx] * num_rows, type=pa.int64()),
                )
            pq.write_table(data_table, str(new_data))

        for cam in camera_keys:
            old_video = src_root / video_path_tmpl.format(video_key=cam, chunk_index=old_chunk, file_index=old_file)
            new_video = output_dir / video_path_tmpl.format(video_key=cam, chunk_index=new_chunk, file_index=new_file)
            new_video.parent.mkdir(parents=True, exist_ok=True)
            if old_video.exists():
                shutil.copy2(str(old_video), str(new_video))

    ep_dir = output_dir / "meta" / "episodes" / "chunk-000"
    ep_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(episodes, str(ep_dir / "file-000.parquet"))

    meta_dir = output_dir / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(tasks, str(meta_dir / "tasks.parquet"))

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
