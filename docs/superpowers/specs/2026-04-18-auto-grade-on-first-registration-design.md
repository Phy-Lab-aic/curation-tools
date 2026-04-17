# Auto-grade ungraded episodes on first dataset registration

**Date:** 2026-04-18
**Scope:** `backend/` — new auto-grade service hooked into the existing `_ensure_*` dataset registration path.

## Problem

Curators manually grade every episode. For obviously-bad rosbag→lerobot conversions where a joint fails to track its command (e.g. `observation.state[13]` diverging from `action[13]` for sustained stretches), the pattern is already detectable from the scalar data. Running that detection once at first registration and setting a suggestive starting grade saves clicks and keeps bad conversions visible in the curation UI.

## Goals

- The first time a dataset is registered in `curation-tools`'s SQLite, auto-set `grade='normal'` + a machine-written `reason` on ungraded episodes whose paired `action[N]` vs `observation.state[N]` divergence contains any severe band.
- Idempotent: subsequent loads of the same dataset do NOT re-auto-grade, even if the user has since changed grades or opened new unscored episodes.
- Never overwrite existing user annotations (any `grade` other than NULL stays as-is, including `reason` and `tags`).

## Non-goals

- No change to the Docker `auto_converter.py` pipeline.
- No new endpoint to re-run auto-grade manually. Idempotency is dataset-wide first-registration only.
- No per-joint threshold UI. Thresholds are fixed (match frontend).
- No machine-written tags (only `grade` and `reason`).

## Design

### Thresholds (match frontend)

Port the logic from `frontend/src/components/ScalarChart.tsx`:
- `MODERATE_RATIO = 0.15`
- `SEVERE_RATIO = 0.30`
- `MIN_SEVERE_RUN = 5` frames
- Ratio: `|action[i] - obs[i]| / max(range(obs), range(act))`
- Pairing: strip `[N]` index suffix; fallback to `observation.state.<name>` ↔ `action.<name>`.

### Hook point

`backend/datasets/services/episode_service.py` already calls:
```
dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
await _ensure_migrated(dataset_id, dataset_service.dataset_path)
```
both in `get_episodes` and `get_episode`. Add `await _ensure_auto_graded(dataset_id, dataset_service.dataset_path)` after migration. It runs once per dataset.

### Idempotency marker

Add column `auto_graded_at TEXT` to the `datasets` table. If NULL, auto-grade runs and the timestamp is written. If non-NULL, skip.

Schema migration: `ALTER TABLE datasets ADD COLUMN auto_graded_at TEXT` inside `db.py` init / migration path — whatever existing convention the repo uses. If the `datasets` table is created fresh, include the column in the CREATE statement. Backfill not needed: existing datasets have already been seen by users, so we leave `auto_graded_at` NULL but treat NULL-with-existing-annotations specially (see below).

### First-registration guard vs existing datasets

Pure "NULL → run once" has a footgun: a dataset that was registered before this feature existed also has `auto_graded_at = NULL`, so first load after upgrade would auto-grade episodes the user *intended* to leave ungraded. Two options:

- **(A)** On feature rollout, stamp `auto_graded_at` to "now" for all existing rows. New datasets get NULL → run → stamp. Old datasets never run.
- **(B)** Add a second column `created_at` and only auto-grade datasets created after this code ships.

**(A) is simpler and matches the "first time we see this dataset" semantic.** Implementation: a one-shot backfill statement `UPDATE datasets SET auto_graded_at = strftime(...) WHERE auto_graded_at IS NULL` runs once at startup alongside the column add.

### Auto-grade service

New file: `backend/datasets/services/auto_grade_service.py` with:

```python
async def ensure_auto_graded(dataset_id: int, dataset_path: Path) -> None
```

Steps:
1. Check `datasets.auto_graded_at` for this `dataset_id`. If non-NULL, return.
2. Walk every episode parquet in the dataset via the same iteration `EpisodeService` uses. For each episode, load `observation.*` scalar columns and `action*` columns (reuse logic in `backend/datasets/routers/scalars.py` or share a helper).
3. For each episode:
   - Pair obs/act keys via `unify_key(k)` (port of frontend `unifyKey`).
   - For each pair, compute bands using `compute_bands(obs, act)` matching frontend.
   - If any band has `level == 'severe'`, collect `(joint_name, severe_frame_count / total)` for the reason string.
4. For each episode with ≥1 severe band and currently ungraded (grade NULL), call `_save_annotation_to_db(...)` with `grade='normal'`, `tags=[]` (preserve any existing tags — but since this is ungraded-only, default `[]`), and the auto reason string.
5. Re-use the parquet write-back pattern from `EpisodeService._write_annotations_to_parquet` to sync changes.
6. Refresh stats: `_refresh_dataset_stats(dataset_id)`.
7. Invalidate caches: `dataset_service.distribution_cache.pop(...)` for the same four keys `update_episode` invalidates.
8. Stamp `datasets.auto_graded_at = now()`.

**Ordering note:** the column add/backfill must run before the dataset registration path first triggers `_ensure_auto_graded`, so put it in the same startup/migration code that runs on DB init.

### Reason format

`[auto] severe divergence: [13] 33.3%, [5] 19.6%, [7] 6.4%`

- Prefix `[auto]` so curators and downstream tools can detect machine-written reasons.
- List top-3 joints by severe-frame ratio descending.
- Joint identifier is the unified key (`[N]`) because it matches the chart label curators see.
- Percentages are severe frames / total episode length, two decimals ending in `%`.

Edge case: if an episode has bands but ONLY after short-run demotion they all became moderate, no severe remains → no auto-grade. This is correct: `grade='normal'` is reserved for genuine tracking failures.

### Error handling

- Parquet read failure on any episode: log warning, skip that episode, continue. Do NOT stamp `auto_graded_at` if the whole pass errored so it can retry on next load.
- If zero episodes qualified for auto-grade, still stamp `auto_graded_at` (the pass ran successfully, nothing to do).
- Exceptions during DB writes: log and propagate; leave `auto_graded_at` NULL to retry.

### Concurrency

Add a per-dataset asyncio lock (or reuse `dataset_service.get_file_lock` pattern) so two simultaneous `get_episodes` calls from the frontend don't both trigger the pass. The lock only needs to serialise the auto-grade pass itself; the regular read path continues.

### Testing

- **Unit:** `compute_bands(obs, act)` matches a few golden fixtures (constant series → []; divergent series → expected bands; short severe demoted). Add a tiny test file `tests/test_auto_grade_bands.py`.
- **Integration:** given a minimal in-memory SQLite + a fixture dataset with known parquet rows, `ensure_auto_graded` stamps the timestamp, auto-grades the expected episodes, skips already-graded ones, and is idempotent on a second call.
- **No regression:** `EpisodeService.get_episode/get_episodes` still works when `auto_graded_at` column didn't exist pre-migration (covered by the startup backfill).

### Rollout

Single PR. First deploy runs the backfill (stamps all existing datasets), then the feature is live for any new dataset that appears. No user-visible change until a new dataset is registered.

## Open questions resolved

- Trigger point: `_ensure_auto_graded` in the registration path, idempotency via `auto_graded_at` column — confirmed simplest reliable place.
- "New dataset only": backfill existing datasets to avoid retroactive grading — confirmed.
- Thresholds: match the frontend's tuned values (0.15/0.30/5-frame run) — confirmed.
- Write path: use existing `_save_annotation_to_db` + parquet writeback; no new code paths for grade persistence.
