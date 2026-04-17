# Grade Reason Capture — Design

**Date:** 2026-04-17
**Status:** Approved (design)

## Goal

Curator users can mark an episode `bad` or `normal` only after providing a written reason. Reasons live in the SQLite metadata DB only — they are **never** written into the dataset parquet files.

## Background

Today the curator supports three grades — `good`, `normal`, `bad` — set via the grade-bar in `DatasetPage.tsx`, the `g`/`n`/`b` keyboard shortcuts, or the bulk "Mark as Bad" context menu in `OverviewTab.tsx`. Grades are persisted to both SQLite (`episode_annotations`) and the underlying parquet via `write_episode_annotations`. There is no place to record *why* an episode was downgraded, which makes downstream review and dataset audits hard.

## Decisions Captured From Brainstorm

| # | Decision |
|---|----------|
| Q1 | Modal popup with autofocus + keyboard-first save (`Cmd/Ctrl+Enter` save, `Esc` cancel). Preserves existing keyboard workflow (`b → reason → enter → next ungraded`). |
| Q2 | Reason is **required** for `bad` and `normal`. Empty / whitespace-only blocked. |
| Q3 | Bulk "Mark as Bad" prompts once and applies the same reason to every selected episode. |
| Q4 | Existing reason is shown beneath the grade-bar; re-clicking the same grade re-opens the modal with the previous reason prefilled. |
| Q5 | Multi-line textarea; Cancel reverts grade change; switching to `good` clears the reason; switching between `bad ↔ normal` opens the modal with empty initial reason. |

## Data Model

**Migration `v1 → v2`** in `backend/core/db.py`:

```sql
ALTER TABLE episode_annotations ADD COLUMN reason TEXT;
```

- Column nullable. NULL when `grade IS NULL` or `grade = 'good'`.
- Application enforces NOT NULL when `grade IN ('normal','bad')`.
- Migration runs in `init_db()` when `PRAGMA user_version < 2`. Existing rows keep `reason = NULL` (historical episodes have no reason — UI tolerates this).
- Parquet schema is **not** modified. `write_episode_annotations()` continues to write only `grade` and `tags`.

## Backend

### Schemas (`backend/datasets/schemas.py`)

- `EpisodeUpdate` — add `reason: str | None = None`
- `BulkGradeRequest` — add `reason: str | None = None`
- `Episode` (response) — add `reason: str | None = None`
- Validator on both request models: when `grade in ('normal','bad')`, `reason` must be a non-empty trimmed string. Raises `ValueError` → FastAPI 422.

### Service (`backend/datasets/services/episode_service.py`)

- `_save_annotation_to_db(dataset_id, episode_index, grade, tags, reason)` — extend signature; include `reason` in INSERT and the `ON CONFLICT DO UPDATE` SET clause.
- `_load_annotations_from_db(dataset_id)` — SELECT `reason` and include it in the per-episode dict.
- `bulk_grade(episode_indices, grade, reason)` — extend signature; pass the same `reason` to every row in the bulk write.
- `update_episode(...)` — pipe `reason` from request through to `_save_annotation_to_db`.
- `write_episode_annotations(...)` — unchanged. Reason is silently dropped from parquet writes.
- When grade transitions to `good` (or `None`), explicitly write `reason = NULL` to the DB so stale reasons don't leak.

### Routers (`backend/datasets/routers/episodes.py`)

- `PUT /episodes/{episode_index}` — pass `update.reason` to the service.
- `POST /episodes/bulk-grade` — pass `req.reason` to the service.
- `GET /episodes` (and any other list endpoint that returns Episode objects) — populate `reason` from the joined annotations.

### Atomicity

Bulk grade writes happen inside a single SQLite transaction. If any row fails validation or write, the transaction is rolled back and the request returns a 4xx — the UI shows the error and no partial state remains.

## Frontend

### Types (`frontend/src/types/index.ts`)

- `Episode` — add `reason: string | null`
- `EpisodeUpdate` — add `reason?: string | null`
- Add `reason?: string` to the bulk-grade payload type.

### New component: `GradeReasonModal.tsx`

```ts
type Props = {
  open: boolean
  grade: 'normal' | 'bad'
  initialReason?: string
  episodeCount?: number          // > 1 → bulk mode
  onSave: (reason: string) => void
  onCancel: () => void
}
```

Behaviour:
- Header: `Mark as Bad` (red) or `Mark as Normal` (yellow), color via `var(--c-red)` / `var(--c-yellow)`.
- Subheader (bulk only): `Apply to {episodeCount} episodes`.
- `<textarea>` autofocus, 4–5 rows, multi-line allowed, prefilled with `initialReason`.
- Footer: `Cancel` button + `Save` button. `Save` disabled while `reason.trim() === ''`.
- Keyboard:
  - `Esc` → `onCancel()`
  - `Cmd/Ctrl+Enter` → `onSave(reason.trim())` (only if non-empty)
  - Plain `Enter` → newline (default textarea behavior)
- Styling: project CSS variables only (`var(--text)`, `var(--c-red)`, etc.). No hardcoded colors.

Reused by both `DatasetPage.tsx` (single episode) and `OverviewTab.tsx` (bulk).

### `DatasetPage.tsx` integration

State:
```ts
const [reasonModal, setReasonModal] = useState<{
  grade: 'normal' | 'bad'
  initialReason: string
  pendingTags: string[]
} | null>(null)
```

Flow:
- Wrap grade entry in `requestGrade(grade)`:
  - `grade === 'good'` → call existing save path with `reason: null`.
  - `grade in ('normal','bad')` → open modal with `initialReason = selectedEpisode.reason ?? ''`, `pendingTags = selectedEpisode.tags`.
- Both grade-bar buttons and `quickGrade(key)` (the `g`/`n`/`b` shortcuts) route through `requestGrade`.
- Modal `onSave(reason)` → `handleSaveEpisode(idx, grade, pendingTags, reason)` → existing auto-jump-to-next-ungraded logic runs.
- Modal `onCancel` → close modal only; grade unchanged; no auto-jump.

`handleSaveEpisode` signature becomes `(index, grade, tags, reason: string | null = null)`. The `reason` is forwarded to `useEpisodes.updateEpisode()`.

Reason display:
- Render `selectedEpisode.reason` (when truthy) as small dim text just beneath the grade-bar. Use `var(--text-dim)` and a smaller font size. No edit affordance — editing happens by clicking the same grade button again.

### `OverviewTab.tsx` integration

State:
```ts
const [bulkReasonModal, setBulkReasonModal] = useState<{
  episodeIndices: number[]
  field: string
  label: string
} | null>(null)
```

Flow:
- "Mark as Bad" context menu click → `setBulkReasonModal({ episodeIndices: indices, ...menuMeta })` instead of posting immediately.
- Modal `onSave(reason)` → `client.post('/episodes/bulk-grade', { episode_indices, grade: 'bad', reason })`.
- Modal `onCancel` → close modal, no API call.

## Edge Cases

| Case | Behaviour |
|------|-----------|
| Modal open, user presses `←`/`→` (episode nav) | Navigation shortcuts disabled while modal is open. |
| Rapid `b` keypress repeats while modal is open | Ignored — modal absorbs keys; `b` typed inside textarea inserts the letter. |
| `g`/`n`/`b` pressed while modal open | Treated as text input; not as a grade shortcut. |
| Bulk request fails midway | Backend rolls back transaction, returns 4xx, UI shows error and modal stays open. |
| Historical row with `grade='bad'` and `reason=NULL` | UI displays no reason text. Re-clicking `Bad` opens modal with empty prefill — user can supply a reason on next save. |
| User switches from `bad` (with reason) → `good` | Backend writes `reason = NULL`. UI removes reason display. |

## Testing

Backend (`tests/`):
- Migration: v1 DB upgraded to v2 retains existing rows, gains `reason` column.
- `PUT /episodes/{idx}`: missing reason for `bad`/`normal` → 422.
- `PUT /episodes/{idx}`: switch to `good` → DB `reason` becomes NULL.
- `POST /episodes/bulk-grade`: same `reason` is applied to every supplied index.
- Parquet snapshot: written parquet file has `grade`/`tags` only, **no** `reason` column.
- `GET /episodes`: response includes `reason` for each episode.

Frontend:
- Unit test `GradeReasonModal`: Save disabled on empty/whitespace; Cmd/Ctrl+Enter triggers save; Esc triggers cancel.
- Component test `DatasetPage`: clicking `bad` opens modal; saving runs auto-jump; cancelling does not.
- Component test `OverviewTab`: bulk Mark-as-Bad opens modal showing episode count; saving fires the API call with reason.

## Out of Scope

- Reason editing without changing grade (no separate "edit reason" UI; user re-clicks the grade).
- Reason history / audit trail (we overwrite, not append).
- Pre-defined reason templates / dropdowns.
- Surfacing reasons in `OverviewTab` charts or tooltips.
- Reasons for `good` grade.
