# Multi-User Curation — Design Spec

- Created: 2026-04-17
- Status: approved, ready for implementation plan
- Scope: enable 5–10 team members to concurrently curate the same LeRobot dataset without edit conflicts, without clobbering each other's work, and without interfering with each other's video playback.

## Goal

Today each PC runs its own `start.sh` with a local SQLite DB at `~/.local/share/curation-tools/metadata.db`, while grade/tags are also written to parquet on shared Synology NFS. This leaks in two directions: annotations diverge between PCs, and parquet on NFS is last-writer-wins across machines with only process-local `asyncio.Lock` protection.

Target behavior:

1. Edits to `grade`, `tags`, `reason`, and `task_instruction` are **shared in real time** across all connected clients.
2. Concurrent edits to the same episode never silently overwrite each other — users are notified and must choose.
3. Video playback (play/pause/seek) is **strictly per-user**. One user pausing does not affect another.
4. High stability and performance for a 5–10 person internal team.

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Topology | Single central FastAPI server on a dedicated workstation (24/7) | Minimal-change path; 5–10 users fits single-worker uvicorn. |
| Source of truth | Server-local SQLite (WAL) on SSD. Postgres-portable schema. | Keeps current stack; can migrate to Postgres later without app rewrite. |
| Real-time transport | Server-Sent Events (SSE) over a single endpoint | Simpler than WebSockets, stable auto-reconnect, fits one-way server→client push. |
| Conflict model | Hybrid: optimistic `version` for `grade`/`tags`; soft lease + `version` for `reason` and `task_instruction` | Short clicks stay fast; long free-text edits are protected. |
| Identity | Name entry on first visit, stored in `localStorage`, sent as `X-User-Name` | Internal team, no spoofing threat model. |
| Parquet | Read-only during curation; written only by a single background exporter | Avoids NFS multi-writer corruption; decouples SoT from artifact. |
| Video | Unchanged — `FileResponse` streamed, all player state is client-local | Per-user independence is naturally preserved. |

Explicitly rejected: SQLite on NFS, centralized SQLite accessed from multiple machines, CRDT-based free-form collab, WebSocket rooms.

## Topology

```
 [PC₁ browser]  [PC₂ browser]  …  [PCₙ browser]
       │              │                 │
       └──────────────┼─────────────────┘
                      │ HTTP (REST + SSE)
                      ▼
      ┌─────────────────────────────────────┐
      │  사내 서버 (24/7, systemd)          │
      │  FastAPI 1 worker (uvicorn)         │
      │  ├─ metadata.db (SQLite WAL, SSD)   │
      │  └─ in-memory SSE pub/sub           │
      └────────┬───────────────────┬────────┘
               │ read-only         │ background
               ▼                   ▼
      ┌───────────────────┐   ┌──────────────────┐
      │ Synology NFS      │   │ Synology NFS     │
      │ data/, videos/    │   │ meta/episodes/   │
      │ (read only)       │   │ (exporter only)  │
      └───────────────────┘   └──────────────────┘
```

- **Single worker** by design. SQLite WAL allows multi-worker reads safely, but the SSE pub/sub lives in-process; a single worker removes the need for inter-process fan-out.
- **SQLite lives on server-local SSD**, never on NFS. The SQLite project explicitly warns that WAL is unsafe on network filesystems.
- **systemd unit** (`curation.service`) keeps the server up across reboots. Nightly `.backup` copy written to a NAS path for snapshots.
- Front-end is served by the same FastAPI from `frontend/dist` (existing SPA fallback path). Clients reach it as `http://curation.local:8001` or direct IP.

## Schema (V3 migration on top of existing V2)

Existing tables unchanged: `datasets`, `dataset_stats`.

### `episode_annotations` — additions

```sql
ALTER TABLE episode_annotations ADD COLUMN version    INTEGER NOT NULL DEFAULT 1;
ALTER TABLE episode_annotations ADD COLUMN updated_by TEXT;
-- updated_at default normalized to CURRENT_TIMESTAMP for Postgres portability.
```

### `task_annotations` — new (task instructions move out of parquet into DB SoT)

```sql
CREATE TABLE task_annotations (
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    task_index INTEGER NOT NULL,
    task       TEXT NOT NULL,
    version    INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,
    PRIMARY KEY (dataset_id, task_index)
);
```

### `edit_leases` — new (soft locks for `reason` and `task_instruction`)

```sql
CREATE TABLE edit_leases (
    resource_type TEXT NOT NULL,      -- 'episode_reason' | 'task_instruction'
    resource_key  TEXT NOT NULL,      -- e.g. "<dataset_id>:<episode_index>"
    owner         TEXT NOT NULL,      -- user name from X-User-Name
    acquired_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    heartbeat_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at    TEXT NOT NULL,      -- acquired_at + 60s; bumped on heartbeat
    PRIMARY KEY (resource_type, resource_key)
);
CREATE INDEX idx_leases_expires ON edit_leases(expires_at);
```

### `audit_log` — new (lightweight history)

```sql
CREATE TABLE audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT DEFAULT CURRENT_TIMESTAMP,
    actor         TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_key  TEXT NOT NULL,
    action        TEXT NOT NULL,      -- update_grade | update_tags | update_reason | update_task | acquire_lease | release_lease | takeover | lease_expired
    payload       TEXT                 -- JSON snapshot
);
```

### Postgres portability notes

- All timestamps use `CURRENT_TIMESTAMP`; no SQLite-specific `strftime`.
- JSON columns stored as `TEXT`; later upgrade to Postgres `JSONB` is a data-only migration.
- `INTEGER PRIMARY KEY AUTOINCREMENT` is the only SQLite-specific construct; swap to `SERIAL`/`GENERATED ALWAYS AS IDENTITY` on Postgres port.

## Edit Protocol

### Policy per field

| Field | Protection | Why |
|---|---|---|
| `grade` | optimistic `version` | single enum, rare conflict |
| `tags` | optimistic `version` | short list, frequent bulk edits |
| `reason` | soft lease + `version` | free text, long sessions |
| `task_instruction` | soft lease + `version` | shared across episodes, high blast radius |

### REST surface

```
PATCH /api/episodes/{index}
  headers: X-User-Name: <name>
  body: { grade?, tags?, reason?, version }
  200: { ...episode, version: n+1 }
  409: { error: "version_mismatch", current: {...}, current_version: n }
  423: { error: "locked_by", owner, expires_at }

PATCH /api/tasks/{index}
  -- same shape, protects task_instruction

POST   /api/leases               { resource_type, resource_key }
  201 { expires_at }
  409 { error: "already_leased_by", owner, expires_at }

POST   /api/leases/heartbeat     { resource_type, resource_key }
  200 { expires_at }
  404 { error: "lease_lost" }

DELETE /api/leases               { resource_type, resource_key }
  204

POST   /api/leases/takeover      { resource_type, resource_key }
  -- force-expire current lease, acquire for caller

GET    /api/events?channel=dataset:<id>
  -- SSE stream (see below)
```

### Lease lifecycle

```
[focus on reason] ──acquire──► lease created (expires_at = now + 60s)
      │
      ├─ every 10s: POST /heartbeat ──► expires_at bumped
      │
      ├─ blur / switch episode ───────► DELETE /leases
      │
      └─ tab closed / network gone ──► heartbeat stops
                                       → 60s later expired by cleanup task
```

Server runs a 60-second periodic task:
```sql
DELETE FROM edit_leases WHERE expires_at < CURRENT_TIMESTAMP;
```

### Save validation order (pseudocode)

```
1. Parse body; require version.
2. If reason changing AND lease for this episode exists AND owner != actor AND not expired
   → return 423.
3. BEGIN IMMEDIATE; SELECT current version FROM episode_annotations.
   (SQLite WAL serializes writers at tx start; Postgres uses SELECT ... FOR UPDATE.)
4. If current.version != body.version → return 409 with current state.
5. UPDATE episode_annotations SET ..., version = version + 1, updated_by = actor.
6. INSERT into audit_log.
7. Publish SSE event.
8. Return 200 with new version.
```

### 409 vs 423 — UX contract

- **409** means someone else already saved. Client shows a quiet banner "외부에서 변경됨 [적용] [버리기]". No auto-overwrite.
- **423** means someone else currently holds the lease. Inputs go read-only with a "User X is typing…" label and a `[takeover]` button.

## Real-time transport

### SSE endpoint

```
GET /api/events?channel=dataset:<dataset_id>
  Content-Type: text/event-stream

Events:
  annotation_updated   { dataset_id, episode_index, grade, tags, reason, version, by }
  task_updated         { dataset_id, task_index, task, version, by }
  lease_changed        { resource_type, resource_key, owner, action }  -- acquired|released|expired
  presence             { dataset_id, viewers: [{ name, focus_episode? }] }
```

- Server maintains a per-connection asyncio queue. On commit, the service layer calls `bus.publish(channel, event)`, which fans out to queues.
- Client uses native `EventSource`. On disconnect, browser auto-reconnects. On reconnect, the client issues one REST refetch of the current dataset to converge state (`Last-Event-ID` not used — simpler and resilient).
- Presence is collected server-side and emitted as a single rolled-up event every 10 seconds, not per-action, to keep the stream quiet.

### Front-end integration

- `useEpisodes` gains an SSE subscriber that mutates React Query cache via `setQueryData`. No extra refetch on normal events.
- For fields the local user is currently editing (focus state), incoming external changes are **not applied to the input** — they land in a `pendingExternalUpdate` flag that surfaces as a small "외부 변경사항 있음 [적용]" banner.

## UX surfaces

### DatasetPage list

- Small dot indicators at row end count current viewers of that episode (1–3 dots, hover tooltip with names). No large avatar stacks.
- If any lease is held for the episode, the `reason` cell shows `(<owner> 편집 중…)` with a small `✎` marker. Grade toggles on that row remain interactive.
- External grade/tags changes fade-flash the cell for ~600 ms. No toast.

### EpisodeEditor

- Header: "보고 있음: TM · JS" (SSE presence).
- Reason textarea acquires a lease on focus, heartbeats every 10 s, releases on blur. When another user holds the lease, the textarea is read-only with "<owner> 편집 중" and a `[takeover]` button.
- Takeover triggers a `lease_changed(expired)` SSE event to the previous owner; their client marks its buffer as "회수당했습니다" and preserves the draft in `localStorage`.
- On a 409 response, a quiet top banner shows "외부 변경사항 — [적용]". Never auto-overwrite.

### VideoPlayer

- No server-side state. Keep current `FileResponse`.
- Add one button: "타임스탬프 복사" → URL param `?t=42.3`. The receiver's client reads `t` at mount and seeks. Still purely client-side.

### Bulk grade

- Preview step: "편집 중인 3개 제외하고 47개 적용".
- If version changed during the request, report "2개 건너뜀 · 재시도" with a link.

### Network resilience

- `reason` input autosaves to `localStorage[draft:ep-<n>]` on each keystroke.
- On reconnect: SSE resumes, single REST refetch of the dataset, and if a draft exists but server value moved, show "저장 안 된 초안 — [이어쓰기] [버리기]".

### Minimalism guardrails

- No enter/leave toasts, no chat, no comment sidebar, no large avatar stacks, no animations on every change.
- Yes to small inline edit markers, 600 ms highlight on external updates, quiet timestamp tooltips.

## Parquet exporter

- SQLite is the source of truth for `grade`, `tags`, `reason`, `task_instruction`.
- A single `asyncio` task started in FastAPI's `lifespan` subscribes to the same SSE bus, collects `dirty_dataset_ids`, and after 15 seconds of idle materializes affected `meta/episodes/chunk-*/file-*.parquet` files and `meta/tasks.parquet` by reusing the current `_write_annotations_to_parquet` logic — just now invoked from exactly one process.
- Because this is the only writer, there is no cross-process contention and the NFS multi-writer risk disappears.
- Failures are logged and retried on the next dirty cycle. Curation UX is unaffected during exporter downtime (DB remains authoritative).

### Exporter endpoints

```
POST /api/export/trigger   → forces a run now
GET  /api/export/status    → { last_run_at, dirty_count, last_error, running }
```

## Migration

One-shot script `scripts/migrate_to_central.py`:

1. Collect per-PC `metadata.db` files via rsync into a staging directory on the central server.
2. For each source DB, merge `episode_annotations` rows into the central DB keyed by `(dataset_path, episode_index)`. Conflicting rows (same key, different values) resolve by `updated_at DESC`; unresolved cases are written to `conflicts.csv` for manual review and skipped.
3. Backfill `task_annotations` from each dataset's `meta/tasks.parquet`.
4. Source DBs are left in place for rollback; they are not modified.

## Rollout

1. Stand up the central server (systemd, SSD DB, backup cron). Run migration script in **read-only dry-run mode** first; inspect `conflicts.csv`.
2. Run the real migration; point one PC at the central server for 2–3 days of solo curation to validate.
3. Move remaining team members over one at a time. Each decommissions their local `./start.sh`.
4. After two weeks of stable operation, clean up `~/.local/share/curation-tools/` on each PC.

## Testing

**Concurrency / integration (pytest + httpx.AsyncClient):**
- `test_concurrent_edit_same_version_409`
- `test_lease_expiry_zombie` (heartbeat stopped → 60 s → other user acquires)
- `test_lease_takeover` (previous owner receives `lease_changed(expired)`)
- `test_bulk_grade_skips_locked`
- `test_sse_reconnect_catchup` (drop SSE, mutate via REST, reconnect, confirm cache converges)
- `test_exporter_debounces_rapid_writes` (N writes in 5 s → 1 parquet write after idle)

**E2E (Playwright, two browser contexts):**
- A edits reason → B sees read-only + owner label.
- A changes grade → B's list row fade-flashes to new value.
- B takeovers → A's buffer flips to "회수당했습니다" and draft is retained.

**Load:**
- k6: 10 VUs for 20 minutes doing `list watch + grade toggle every 10 s + video seek every 1 s`. Pass thresholds: `409 rate < 5%`, PATCH P95 `< 200 ms`, zero 500s.

## Observability

Extend `/api/health`:

```json
{
  "status": "ok",
  "sse_connections": 7,
  "active_leases": 2,
  "conflicts_last_hour": 3,
  "exporter": { "dirty": 0, "last_run_at": "...", "last_error": null }
}
```

Log at INFO level only: `conflict_rate`, lease transitions, SSE reconnects, exporter runs.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Single server down | systemd `Restart=always`, daily DB snapshot to NAS, trivial to swap host. |
| SQLite hits write-throughput ceiling | Single-writer WAL comfortably handles 10 users with sub-second edits. Postgres migration path preserved. |
| Lease holder crashes, others blocked | 60 s TTL + periodic cleanup; `takeover` always available. |
| Migration conflicts across per-PC DBs | Dry-run first, `conflicts.csv` for manual review, source DBs retained. |
| Exporter falls behind | Curation continues (DB is SoT); status surfaced via `/api/export/status`; `POST /api/export/trigger` forces a run. |
| Name spoofing via `X-User-Name` | Accepted — internal trusted team; audit log still records whatever was sent. |
