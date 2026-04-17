# Design: Integrate cycle-boundary stamping into the curator workflow

**Date:** 2026-04-17
**Status:** Draft (awaiting user review)
**Owner:** curation-tools

## Problem

Cycle boundaries are encoded in lerobot parquet data as `is_terminal=True` on gripper-cycle completion frames, and the curator UI (`DatasetPage` terminal-bar + `VideoPlayer` tick marks, backed by `backend/datasets/routers/scalars.py`) already reads this column. Today the column is stamped by an external script in a sibling repo (`lerobot_dataset_helper/update_dataset_flags.py`). Operators have to leave the curator app, run the script by hand, and come back — and each run silently rewrites parquet files with no in-app affordance for inspection or re-running. The workflow asked for is: "let me stamp cycles from inside the curator app."

## Goal

Add a fourth operation to the existing `TrimPanel` — **Cycles** — that stamps `is_terminal` and `is_last` on the active dataset's parquet files, via the same async job pattern as `split` / `merge` / `delete`. Reuses the detection logic from `update_dataset_flags.py` verbatim; no new algorithms.

## Non-goals

- Configurable gripper thresholds / channel indices in the UI. Keep the hardcoded constants from the script (`LEFT_GRIPPER_IDX=7`, `RIGHT_GRIPPER_IDX=15`, closed<0.5, open>0.8). Can be exposed later if a second robot type needs it.
- Cross-dataset batch stamping from CellPage. Single-dataset only.
- Derived-dataset output. Op is in-place — no copy produced. Operators who need a backup should take one themselves.
- Changing the scalars router or the UI rendering of terminal frames. Those already work.

## Contract

**HTTP:** `POST /api/datasets/stamp-cycles`

Request body:
```json
{ "source_path": "/mnt/.../HZ_seqpick_deodorant", "overwrite": false }
```

Response (202 Accepted):
```json
{ "job_id": "uuid", "operation": "stamp_cycles", "status": "queued" }
```

Status polled via the existing `GET /api/datasets/ops/status/{job_id}`, which already returns `{status, error, result_path}`. `result_path` is set to the source dataset path (in-place).

**Pre-flight guard:** If the dataset's parquet files already contain `is_terminal` *and* `overwrite=false`, the job fails fast with `error="already_stamped"`. The UI detects this before submitting (via a new cheap `GET /api/datasets/stamp-cycles/status?path=...`) and prompts the user to confirm re-stamping.

## Backend structure

New service: `backend/datasets/services/cycle_stamp_service.py`

- Public: `async def stamp_cycles(source_path: str, overwrite: bool) -> str` (returns job_id, runs the actual work in a background task using the existing `dataset_ops_service` job registry).
- Port `update_dataset_flags.update_flags` verbatim. Inline the two helpers from `lerobot_dataset_helper` (`add_field_to_data_parquet`, `delete_field_from_data_parquet`, `_resolve_dataset_path`, `_collect_data_parquet_files`) rather than taking a new dep — their logic is small and copying avoids dragging in a repo outside curation-tools' control.
- Pre-flight: open first parquet's schema, check for `is_terminal`. If present and `overwrite=False`, mark job `failed` with `error="already_stamped"`.
- After write, invalidate the dataset_service cache for `source_path` so the curator picks up the new column without a manual reload.

New status endpoint: `GET /api/datasets/stamp-cycles/status?path=...`

- Cheap: reads only schema + a coarse count (sum of `is_terminal` True from first parquet) to say `{ "stamped": bool, "is_terminal_count_sample": int }`. Lets the UI decide whether to surface a confirmation.

Router: extend `backend/datasets/routers/dataset_ops.py` with `StampCyclesRequest` schema and both endpoints. No new router file.

## Frontend structure

`frontend/src/components/TrimPanel.tsx`:

- Extend `TabId` to `'split' | 'merge' | 'delete' | 'cycles'`.
- Add `<CyclesTab datasetPath={...}>` component (lives in the same file to match `SplitTab` / `MergeTab` / `DeleteTab`).
- `CyclesTab` lifecycle:
  1. On mount, `GET /api/datasets/stamp-cycles/status?path=<datasetPath>`; show "Not stamped yet" or "Already stamped — N is_terminal flags detected (sample)".
  2. Primary button: "Stamp cycles".
  3. If already stamped → clicking opens a confirm modal ("This will rewrite parquet files in place. Overwrite existing cycle markers?") before submission.
  4. Submit calls `POST /api/datasets/stamp-cycles` with `overwrite` set from the modal's answer; uses the shared `useJobPoller` hook already in the file.
  5. On `completed`, show "Done — N frames stamped" and link (hint) to reload the episode to see new markers.

No changes to `DatasetPage` or `VideoPlayer` — they already render the markers that the new column produces.

## Safety

- **In-place write** is documented in the UI button copy ("rewrites data parquet files in place — no backup is taken").
- **Pre-flight detection** prevents accidental double-stamping; overwrite requires explicit confirmation.
- **Path validation** — reuse `_validate_path` from `dataset_ops.py`. The service rejects paths outside `allowed_dataset_roots` (same policy as split/merge/delete).
- **Atomic write per file** — confirmed by inspection: `add_field_to_data_parquet` writes `<file>.tmp` then `os.replace()` swaps it in. Each parquet flip is atomic; a mid-run crash leaves some files old and some new but never corrupts a single file.

## Tests

Backend:
- `tests/test_cycle_stamp_service.py`:
  - happy path: fresh dataset with no is_terminal → after stamp, schema contains `is_terminal` + `is_last`, expected cycle-count on a crafted gripper trace.
  - pre-flight rejects: already-stamped + `overwrite=false` → job fails with `already_stamped`.
  - overwrite path: already-stamped + `overwrite=true` → replaces column with fresh values.
  - symmetric with `update_dataset_flags.py`: run both on the same fixture; counts and frame indices match.
- `tests/test_dataset_ops_router.py`: extend to cover the new POST / GET endpoints (202 on submit, 404 on unknown path, status payload shape).

Frontend:
- No component tests exist in the repo today (only backend pytests). Manual smoke check via the running app.

E2E (optional, follow-up): headless playwright flow — open cell002, go to Trim → Cycles, submit, wait for completion, verify terminal-bar chips appear. `tests/test_e2e.py` already has the playwright harness this can plug into.

## Decisions

1. ~~Atomicity~~ — resolved: helper does tmp-file + `os.replace()` per parquet.
2. **Cycles tab scope**: dataset-scoped (gated on `datasetPath`, like Split and Delete). Merge is global because it lists multiple datasets; stamping acts on one active dataset only.
3. **DB cache**: call `dataset_service.invalidate(source_path)` on job success so a reloaded episode pulls the fresh schema without a server restart.

## Acceptance

- Operator opens cell002 → `HZ_seqpick_deodorant` in the curator, clicks **Trim → Cycles → Stamp cycles**, waits for "completed", reloads an episode. Terminal-bar now shows cycle-end chips and the scrubber shows red tick marks, with no external scripts run.
- If they click Stamp a second time without Overwrite confirmation, the UI refuses and asks them to confirm.
- Unit + router tests green, lsp diagnostics clean on touched files.
