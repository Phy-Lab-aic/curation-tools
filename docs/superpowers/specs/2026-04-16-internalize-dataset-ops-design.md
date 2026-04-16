# Internalize Dataset Operations (lerobot dependency removal)

**Date:** 2026-04-16
**Status:** Approved

## Problem

`dataset_ops_service.py` imports lerobot's `LeRobotDataset`, `delete_episodes`, `split_dataset`, `merge_datasets` at runtime. These functions do parquet/json/video file manipulation that can be implemented directly with pyarrow (already a dependency). Removing lerobot eliminates a heavy, unnecessary dependency.

## Decision

Complete removal of all lerobot imports. Replace with a single internal engine module using pyarrow for direct file manipulation.

## Architecture

### New File: `backend/datasets/services/dataset_ops_engine.py`

Pure functions for dataset file manipulation. No async, no job tracking — just `input_dir -> output_dir` transforms.

#### Common Utilities

| Function | Purpose |
|----------|---------|
| `read_info(root)` | Read `meta/info.json` |
| `read_episodes(root)` | Read all `meta/episodes/chunk-*/file-*.parquet` into single Table |
| `read_tasks(root)` | Read `meta/tasks.parquet` |
| `discover_data_files(root, episode_index)` | Find `data/chunk-*/episode_NNNNNN.parquet` for an episode |
| `discover_video_files(root, episode_index)` | Find all video files for an episode across camera keys |
| `reindex_episodes(episodes)` | Reassign `episode_index` 0..N, recompute `dataset_from_index`, `dataset_to_index`, `data/chunk_index`=0, `data/file_index`=episode_index, update `videos/*` paths |
| `write_dataset(output_dir, info, episodes, tasks, video_map)` | Write complete dataset structure to output_dir |

#### Core Operations

```
delete_episodes(dataset_root, episode_ids, output_dir) -> Path
split_dataset(dataset_root, episode_ids, output_dir) -> Path
merge_datasets(dataset_roots, output_dir) -> Path
```

### Modified File: `backend/datasets/services/dataset_ops_service.py`

Minimal changes — replace lerobot imports with engine imports in `_run_*` methods.

**Removed:**
- All `from lerobot.*` imports (4 locations)
- `_make_writable_mirror()` (HF cache workaround, no longer needed)
- `_set_writable_cache()` (same reason)

**Added:**
- Import from `dataset_ops_engine`
- Backup/restore pattern for in-place operations

**Unchanged:**
- Async job tracking infrastructure
- Public API signatures
- `split_and_merge` (calls engine split then engine merge)

### In-Place Backup/Restore Pattern

When `output_dir` is None (in-place operation):

1. Rename `source` to `source.bak`
2. Call engine function: `source.bak` -> `source`
3. Success: delete `source.bak`
4. Failure: delete partial `source`, rename `source.bak` back to `source`

Engine functions always operate as pure `input -> output` transforms.

## Dataset Format (LeRobot v3.0)

```
dataset_root/
├── meta/
│   ├── info.json                          # fps, robot_type, total_episodes, features
│   ├── tasks.parquet                      # task_index, task
│   └── episodes/
│       └── chunk-NNN/
│           └── file-NNN.parquet           # episode metadata (multi-chunk supported)
├── data/
│   └── chunk-NNN/
│       └── episode_NNNNNN.parquet         # per-episode observation/action data
└── videos/
    └── chunk-NNN/
        └── observation.images.*/
            └── episode_NNNNNN.mp4
```

### Chunk Strategy

- **Read:** Scan all chunks, load into unified table
- **Write:** Output to single chunk (chunk-000). Reindex makes original chunk boundaries meaningless.

### Episode Reindexing

| Column | Update Rule |
|--------|-------------|
| `episode_index` | Sequential from 0 |
| `dataset_from_index` | Cumulative sum of `length` |
| `dataset_to_index` | `from_index + length` |
| `data/chunk_index` | All 0 (single output chunk) |
| `data/file_index` | Same as `episode_index` |
| `videos/*` columns | Updated to new chunk/episode paths |
| `length`, `task_index`, `grade`, `tags`, `serial_number` | Preserved as-is |

### Merge Compatibility

Before merging, validate:
- `fps` must match across all sources
- `robot_type` must match
- `features` schema must be compatible

Tasks are concatenated and deduplicated; `task_index` remapped in episodes accordingly.

### Video File Handling

All operations use **copy** (not move or symlink). Original datasets are never modified (except in-place delete via backup/restore).

## Files Changed

| File | Change |
|------|--------|
| `backend/datasets/services/dataset_ops_engine.py` | **New** — pure parquet/video/meta manipulation |
| `backend/datasets/services/dataset_ops_service.py` | Replace lerobot calls with engine calls; add backup/restore |
| `tests/test_dataset_ops_engine.py` | **New** — integration tests with real parquet fixtures |
| `tests/test_dataset_ops_service.py` | Remove lerobot mock fixture; mock engine instead |

## Files Unchanged

- `backend/datasets/routers/dataset_ops.py` — API unchanged
- `frontend/src/components/TrimPanel.tsx` — UI unchanged
- All other services — no dependency on lerobot

## Test Plan

### Engine Tests (`test_dataset_ops_engine.py`)

- Delete: middle episodes removed, reindex correct, videos copied
- Split: selected episodes extracted, new dataset structure valid
- Merge: two datasets combined, episode/task reindex correct
- Merge validation: mismatched fps raises error
- Multi-chunk: episodes across multiple chunks handled correctly
- Edge cases: delete all, empty selection, single episode

### Service Tests (`test_dataset_ops_service.py`)

- Job tracking: create, poll, complete lifecycle
- In-place backup/restore on failure
- Engine mocked — tests focus on async job infrastructure
