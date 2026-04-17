# Good-only dataset sync via absolute destination path

**Date:** 2026-04-18
**Status:** Draft (awaiting user review)
**Owner:** `curation-tools` UI/API + `rosbag-to-lerobot` shared dataset ops

## Problem

The current split / merge flow in `curation-tools` owns too much filesystem policy:

- it distinguishes "new dataset" vs "existing dataset" in the UI
- it owns the actual split / merge implementation locally
- it allows unsafe or misleading cases such as choosing the source dataset as the merge target

The desired workflow is closer to a curated sync:

- only `good` episodes are eligible
- operators may optionally narrow those `good` episodes by `tag`
- operators provide one absolute destination path
- if the destination does not exist, create a new LeRobot dataset there
- if the destination already is a LeRobot dataset, merge into it
- if the destination exists but is not a LeRobot dataset, fail

That policy belongs closer to the LeRobot conversion / dataset-management layer in the sibling repo `rosbag-to-lerobot`, not duplicated inside `curation-tools`.

## Goals

- Keep `curation-tools` as the operator-facing UI and async job API.
- Move dataset sync policy and filesystem mutation logic into a shared implementation owned by `rosbag-to-lerobot`.
- Replace the current "new vs existing" destination model with a single absolute destination path.
- Restrict the split flow to `grade == good`, with optional tag filtering inside that good subset.
- On merge, skip duplicates by `Serial_number` instead of appending them again.
- Reject self-merge (`source_path == destination_path`) before any data mutation.

## Non-goals

- No relative destination paths.
- No generic grade selection UI for split. `good` is fixed.
- No standalone merge tab redesign in this change; this spec is about the good-only sync flow from the active dataset.
- No new dependency publication or packaging work beyond the minimum needed to reuse the shared implementation.
- No automatic deletion from the source dataset after sync.

## Ownership boundary

### `curation-tools`

- Shows the sync UI in `TrimPanel`.
- Computes the selected `episode_ids` from the loaded dataset metadata.
- Validates that the destination input is non-empty and absolute before dispatch.
- Runs async job orchestration and status polling.
- Reports summary results to the user (`created`, `skipped_duplicates`, `destination_path`, `mode`).

### `rosbag-to-lerobot`

- Owns the reusable dataset sync implementation.
- Validates destination dataset shape and merge compatibility.
- Creates a new LeRobot dataset when the destination path does not exist.
- Merges into an existing LeRobot dataset when the destination path already exists.
- Skips duplicate episodes by `Serial_number`.
- Rejects self-merge and invalid destination directories.

This keeps the UI in `curation-tools`, while the dataset mutation policy lives in the repo that already owns LeRobot dataset production and maintenance.

## User-facing behavior

The Split tab becomes a good-only sync tab:

- Grade selection UI is removed.
- The operator may optionally choose one or more tags.
- Matching episodes are:
  - all episodes with `grade == "good"` when no tag is selected
  - only episodes with `grade == "good"` and at least one selected tag when tags are selected
- The destination UI is one text input for an absolute path.
- There is no "new dataset" / "existing dataset" toggle.

Submission behavior:

- destination path does not exist: create a new dataset at that exact path
- destination path exists and is a LeRobot dataset: merge missing good episodes into it
- destination path exists and is not a LeRobot dataset: fail fast

## Contract

### Frontend -> backend request

`POST /api/datasets/split-into`

Request body becomes conceptually:

```json
{
  "source_path": "/mnt/.../source_dataset",
  "episode_ids": [1, 4, 9],
  "destination_path": "/mnt/.../good_dataset_sync"
}
```

`target_name`, `target_path`, and `output_dir` are removed from the operator-facing sync path. The server derives create-vs-merge from the destination path state.

### Job status payload

The existing job status endpoint stays in place, but successful sync jobs add a result summary:

```json
{
  "job_id": "uuid",
  "operation": "sync_good_episodes",
  "status": "complete",
  "result_path": "/mnt/.../good_dataset_sync",
  "summary": {
    "mode": "create",
    "created": 12,
    "skipped_duplicates": 3
  }
}
```

`mode` is `"create"` when the destination did not exist and `"merge"` when it already existed as a LeRobot dataset.

## Shared implementation shape

Add a reusable sync module in `rosbag-to-lerobot` that `curation-tools` calls from its backend as a Python API, not a shell-oriented CLI glue layer.

Integration choice for this design:

- `rosbag-to-lerobot` exposes the sync implementation as a normal Python module inside that repo.
- `curation-tools` gets a config setting pointing at the sibling `rosbag-to-lerobot` checkout root.
- `curation-tools` loads the shared module from that configured checkout at process startup.
- No wheel publication or subprocess wrapper is introduced for this feature.

Proposed logical entrypoint:

```python
def sync_good_episodes(
    source_dataset: Path,
    episode_ids: list[int],
    destination_path: Path,
) -> SyncResult:
    ...
```

Where `SyncResult` contains:

- `mode: Literal["create", "merge"]`
- `destination_path: str`
- `created: int`
- `skipped_duplicates: int`

Internally the shared implementation may reuse the existing split / merge engine ideas, but the public contract is path-driven sync, not separate split and merge verbs.

## Validation rules

The shared implementation must enforce all of the following:

- `destination_path` must be absolute.
- `source_dataset` must exist and be a valid LeRobot dataset.
- `destination_path == source_dataset` is rejected.
- existing destination without `meta/info.json` is rejected.
- existing destination must be merge-compatible with source:
  - same `fps`
  - same `robot_type`
- source and destination must remain under allowed dataset roots once called from `curation-tools`.

## Duplicate handling

Duplicate detection is based on `Serial_number`.

- Read all destination episode serials before merge.
- For each selected source episode:
  - if its `Serial_number` already exists in destination, skip it
  - otherwise include it in the output batch

If every selected episode is already present:

- the job still succeeds
- `created = 0`
- `skipped_duplicates = len(selected_episodes)`

This is intentionally sync-like behavior, not strict append behavior.

## Failure behavior

Fail before any mutation when:

- destination path is relative
- destination path exists but is not a LeRobot dataset
- destination path equals source path
- selected episode set is empty
- merge compatibility check fails

When a create or merge operation fails after work has started, destination writes must preserve the same backup / restore guarantees already used for in-place dataset mutation paths.

## Backend changes in `curation-tools`

### Router

`backend/datasets/routers/dataset_ops.py`

- replace the current split-into request model for the operator sync path with `destination_path`
- validate that `destination_path` is absolute and inside allowed roots
- reject source==destination before dispatch
- rename the operation returned by this path to something explicit such as `sync_good_episodes`

### Service

`backend/datasets/services/dataset_ops_service.py`

- replace `_run_split_and_merge(...)` for this path with a worker that calls the shared `rosbag-to-lerobot` sync implementation
- store job summary counts (`created`, `skipped_duplicates`, `mode`) in the job record

## Frontend changes in `curation-tools`

`frontend/src/components/TrimPanel.tsx`

- remove grade toggles from the split flow
- keep tag selection, but only as a refinement inside the `good` subset
- remove destination mode toggle (`new` / `existing`)
- replace dataset dropdown / target name fields with one absolute-path text input
- disable submission when:
  - destination path is empty
  - no `good` episodes match the current tag filter
  - a job is already running
- show result copy that distinguishes:
  - newly copied episodes
  - skipped duplicates
  - final destination path

## Tests

### `rosbag-to-lerobot`

- create-new sync when destination path does not exist
- merge sync when destination is an existing LeRobot dataset
- reject existing plain directory without LeRobot metadata
- reject self-merge
- skip duplicate serial numbers during merge
- return `created=0` when all selected episodes are duplicates

### `curation-tools`

- router accepts only absolute destination paths
- router rejects source==destination
- service stores sync summary in job status
- UI only syncs `good` episodes
- UI tag filter narrows only within the `good` subset
- UI no longer exposes "new dataset" / "existing dataset" controls for this flow

## Rollout sequence

1. Implement and test the shared sync module in `rosbag-to-lerobot`.
2. Update `curation-tools` backend to call that shared module.
3. Simplify the `TrimPanel` UI to match the new path-driven contract.
4. Verify end-to-end:
   - create new destination
   - merge into existing destination
   - duplicate skip counts
   - rejection of invalid destination directories

## Open questions resolved

- **Where does the filesystem policy live?**
  `rosbag-to-lerobot` owns it.
- **What destination format is allowed?**
  Absolute paths only.
- **What if the destination exists but is not a dataset?**
  Reject with an error.
- **Can users sync non-good grades?**
  No. `good` only.
- **How do tags interact with grade?**
  Tags refine only within `good`.
- **How are duplicates handled?**
  Skip by `Serial_number`.
