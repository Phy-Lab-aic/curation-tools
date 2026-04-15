# SQLite Metadata Layer Design

## Goal

Introduce SQLite as a metadata index layer for RoboData Studio. The DB caches dataset registry info, replaces JSON sidecar files for curation annotations (grade/tags), and enables cross-dataset search queries. Existing parquet-based data reading is unchanged.

## Architecture

```
[Router] -> [Service] -> [DB Layer (aiosqlite)] -> SQLite (local)
                     \-> [Parquet / NAS]           (data reads unchanged)
```

- **DB location:** `~/.local/share/curation-tools/metadata.db` (configurable via `CURATION_DB_PATH`)
- **Single file:** `backend/core/db.py` handles connection, schema creation, and version migration
- **Async:** Uses `aiosqlite` to match existing async service layer
- **Sync strategy:** Lazy — DB is populated/refreshed when user navigates to a cell or dataset, not on startup

## Schema (3 tables)

### datasets

Registered dataset cache. Populated on first access, refreshed on subsequent visits.

```sql
CREATE TABLE IF NOT EXISTS datasets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    cell_name       TEXT,
    fps             INTEGER DEFAULT 0,
    total_episodes  INTEGER DEFAULT 0,
    robot_type      TEXT,
    features        TEXT,                    -- JSON string
    registered_at   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    synced_at       TEXT                     -- last filesystem scan timestamp
);
```

### episode_annotations

Per-episode curation data. Replaces JSON sidecar files.

```sql
CREATE TABLE IF NOT EXISTS episode_annotations (
    dataset_id      INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    episode_index   INTEGER NOT NULL,
    grade           TEXT CHECK(grade IN ('good', 'normal', 'bad')),
    tags            TEXT DEFAULT '[]',       -- JSON array
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (dataset_id, episode_index)
);
```

### dataset_stats

Aggregated curation statistics for cross-dataset queries.

```sql
CREATE TABLE IF NOT EXISTS dataset_stats (
    dataset_id          INTEGER PRIMARY KEY REFERENCES datasets(id) ON DELETE CASCADE,
    graded_count        INTEGER DEFAULT 0,
    good_count          INTEGER DEFAULT 0,
    normal_count        INTEGER DEFAULT 0,
    bad_count           INTEGER DEFAULT 0,
    total_duration_sec  REAL DEFAULT 0,
    good_duration_sec   REAL DEFAULT 0,
    normal_duration_sec REAL DEFAULT 0,
    bad_duration_sec    REAL DEFAULT 0,
    updated_at          TEXT
);
```

## Schema Versioning

No migration framework. Uses SQLite `PRAGMA user_version`:

```python
async def init_db():
    db = await get_db()
    version = (await db.execute_fetchone("PRAGMA user_version"))[0]
    if version < 1:
        await db.executescript(SCHEMA_V1)
        await db.execute("PRAGMA user_version = 1")
    # Future: if version < 2: apply V2 migration, set user_version = 2
```

Called from `main.py` lifespan on app startup.

## Sync Strategy: Lazy

DB is NOT pre-populated on startup. Instead, data flows into the DB on first access:

### Dataset registration (cell_service)

1. User opens cell page -> `get_datasets_in_cell(cell_path)` called
2. Service scans NAS filesystem (existing logic)
3. For each discovered dataset: `INSERT OR REPLACE INTO datasets` with current metadata
4. Update `synced_at` timestamp
5. Return data from DB

On subsequent calls, check `synced_at`. If recent enough (within current session), serve from DB. Otherwise re-scan.

### Annotation read/write (episode_service)

**Read:** Query `episode_annotations` WHERE dataset_id + episode_index. Merge with parquet base data (same as current sidecar merge, different source).

**Write:** `INSERT OR REPLACE INTO episode_annotations`. Then update `dataset_stats` aggregates.

## Sidecar Migration

On first annotation read for a dataset:

1. Check if `episode_annotations` has any rows for this `dataset_id`
2. If no rows AND a JSON sidecar file exists for this dataset path:
   - Read JSON sidecar using existing `_load_sidecar()` logic
   - Bulk insert all entries into `episode_annotations`
   - Recompute `dataset_stats`
3. JSON file is NOT deleted (serves as backup)
4. Subsequent reads hit DB directly (migration is one-time per dataset)

## Cross-Dataset Search API

New endpoint:

```
GET /api/datasets/search?min_good_ratio=0.7&robot_type=so100&cell=cell_a
```

Query parameters (all optional):
- `min_good_ratio` — minimum good/(good+normal+bad) ratio
- `robot_type` — exact match
- `cell` — cell_name filter
- `min_episodes` — minimum total_episodes

Returns `list[DatasetSummary]` (same schema as existing cell dataset listing).

Implementation: `SELECT datasets.* FROM datasets JOIN dataset_stats ON ...` with WHERE clauses.

## Service Changes

### core/db.py (NEW)

- `get_db() -> aiosqlite.Connection` — singleton connection, created on first call
- `init_db()` — create tables, run migrations
- `close_db()` — close connection (called from lifespan shutdown)

### core/config.py (MODIFY)

Add one field:
```python
db_path: str = ""  # empty = default ~/.local/share/curation-tools/metadata.db
```

### main.py (MODIFY)

Add `init_db()` / `close_db()` to lifespan:
```python
async with lifespan(app):
    await init_db()
    yield
    await close_db()
```

### cell_service.py (MODIFY)

- `scan_cells()` — after scanning, upsert results into `datasets` table
- `get_datasets_in_cell()` — after scanning, upsert. Stats come from `dataset_stats` instead of re-reading parquet + sidecar every time
- Remove `_count_grades()` — replaced by `dataset_stats` table lookups

### episode_service.py (MODIFY)

- Replace `_load_sidecar()` / `_save_sidecar()` with DB read/write
- Keep `_load_sidecar()` renamed to `_load_sidecar_json()` for migration-only use
- Add `_ensure_migrated()` — auto-migrate JSON on first access
- Add `_refresh_dataset_stats()` — recompute stats after grade changes
- `update_episode()` / `bulk_grade()` — write to DB, update stats, invalidate distribution cache

### datasets router (MODIFY)

- Add `GET /api/datasets/search` endpoint

### export_service.py (MODIFY)

- Currently imports `_load_sidecar()` to read grades for filtering. Change to query `episode_annotations` from DB instead.
- Minor change: replace sidecar read with DB query, same filtering logic.

## What Does NOT Change

- `dataset_service.py` — parquet loading logic unchanged
- `task_service.py` — tasks.parquet read/write unchanged
- `fields_service.py` — info.json + parquet column management unchanged
- `distribution_service.py` — reads from episode_service which now reads from DB (transparent)
- All routers except datasets (search endpoint)
- Frontend — API response shapes are identical

## Dependencies

Add to `pyproject.toml`:
```toml
aiosqlite >= 0.20.0
```

## Testing

- Unit tests for `core/db.py`: schema creation, version migration
- Unit tests for sidecar migration logic
- Integration tests for cell_service DB upsert
- Integration tests for episode annotation DB round-trip
- Existing mock-based tests continue to work (services still expose same interface)
