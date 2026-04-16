# SQLite Metadata Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add SQLite as a metadata index layer — dataset registry cache, annotation storage (replacing JSON sidecars), and cross-dataset search.

**Architecture:** `backend/core/db.py` provides async DB connection via aiosqlite. Services write metadata to SQLite on first access (lazy sync). Annotations (grade/tags) move from JSON sidecar files to the `episode_annotations` table, with automatic one-time migration. A `dataset_stats` table enables cross-dataset search queries.

**Tech Stack:** Python 3.10+, aiosqlite, SQLite3, FastAPI, pytest

**Spec:** `docs/superpowers/specs/2026-04-15-sqlite-metadata-layer-design.md`

**Important — file locations:** The backend uses domain-based modules. Services live at `backend/datasets/services/`, routers at `backend/datasets/routers/`, core at `backend/core/`. Backwards-compat shims exist at old paths (`backend/services/`, `backend/routers/`) but all new code should import from domain paths.

---

### Task 1: Add aiosqlite dependency and create core/db.py

**Files:**
- Modify: `pyproject.toml`
- Modify: `backend/core/config.py`
- Create: `backend/core/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Install aiosqlite**

Run: `pip install "aiosqlite>=0.20.0"`

- [ ] **Step 2: Add aiosqlite to pyproject.toml**

In `pyproject.toml`, add `aiosqlite` to the dependencies list:

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pyarrow>=17.0.0",
    "rerun-sdk>=0.22.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "watchdog>=4.0.0",
    "aiosqlite>=0.20.0",
]
```

- [ ] **Step 3: Add db_path to config**

In `backend/core/config.py`, add one field to `Settings`:

```python
db_path: str = ""  # empty = default ~/.local/share/curation-tools/metadata.db
```

- [ ] **Step 4: Write failing test for db.py**

Create `tests/test_db.py`:

```python
"""Tests for core/db.py — schema creation, connection lifecycle, version migration."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from backend.core.db import get_db, init_db, close_db, _reset


@pytest.fixture(autouse=True)
def tmp_db(monkeypatch):
    """Point DB to a temp file for each test."""
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    yield tmp
    asyncio.get_event_loop().run_until_complete(close_db())
    _reset()
    tmp.unlink(missing_ok=True)


class TestInitDb:
    @pytest.mark.asyncio
    async def test_creates_tables(self, tmp_db):
        await init_db()
        db = await get_db()
        tables = await db.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = [t[0] for t in tables]
        assert "datasets" in names
        assert "episode_annotations" in names
        assert "dataset_stats" in names

    @pytest.mark.asyncio
    async def test_sets_user_version(self, tmp_db):
        await init_db()
        db = await get_db()
        row = await db.execute_fetchone("PRAGMA user_version")
        assert row[0] == 1

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_db):
        await init_db()
        await init_db()  # should not raise
        db = await get_db()
        row = await db.execute_fetchone("PRAGMA user_version")
        assert row[0] == 1


class TestGetDb:
    @pytest.mark.asyncio
    async def test_returns_same_connection(self, tmp_db):
        await init_db()
        db1 = await get_db()
        db2 = await get_db()
        assert db1 is db2

    @pytest.mark.asyncio
    async def test_close_and_reopen(self, tmp_db):
        await init_db()
        db1 = await get_db()
        await close_db()
        _reset()
        await init_db()
        db2 = await get_db()
        assert db1 is not db2


class TestSchema:
    @pytest.mark.asyncio
    async def test_datasets_table_columns(self, tmp_db):
        await init_db()
        db = await get_db()
        rows = await db.execute_fetchall("PRAGMA table_info(datasets)")
        col_names = [r[1] for r in rows]
        assert "id" in col_names
        assert "path" in col_names
        assert "name" in col_names
        assert "cell_name" in col_names
        assert "fps" in col_names
        assert "total_episodes" in col_names
        assert "robot_type" in col_names
        assert "features" in col_names
        assert "synced_at" in col_names

    @pytest.mark.asyncio
    async def test_episode_annotations_table_columns(self, tmp_db):
        await init_db()
        db = await get_db()
        rows = await db.execute_fetchall("PRAGMA table_info(episode_annotations)")
        col_names = [r[1] for r in rows]
        assert "dataset_id" in col_names
        assert "episode_index" in col_names
        assert "grade" in col_names
        assert "tags" in col_names

    @pytest.mark.asyncio
    async def test_grade_check_constraint(self, tmp_db):
        await init_db()
        db = await get_db()
        await db.execute(
            "INSERT INTO datasets (path, name) VALUES (?, ?)",
            ("/tmp/test", "test"),
        )
        await db.commit()
        with pytest.raises(Exception):
            await db.execute(
                "INSERT INTO episode_annotations (dataset_id, episode_index, grade) VALUES (1, 0, 'invalid')"
            )
            await db.commit()

    @pytest.mark.asyncio
    async def test_cascade_delete(self, tmp_db):
        await init_db()
        db = await get_db()
        await db.execute("INSERT INTO datasets (path, name) VALUES ('/tmp/x', 'x')")
        await db.execute(
            "INSERT INTO episode_annotations (dataset_id, episode_index, grade) VALUES (1, 0, 'good')"
        )
        await db.execute(
            "INSERT INTO dataset_stats (dataset_id, good_count) VALUES (1, 1)"
        )
        await db.commit()
        await db.execute("DELETE FROM datasets WHERE id = 1")
        await db.commit()
        ann = await db.execute_fetchone("SELECT COUNT(*) FROM episode_annotations")
        stats = await db.execute_fetchone("SELECT COUNT(*) FROM dataset_stats")
        assert ann[0] == 0
        assert stats[0] == 0
```

- [ ] **Step 5: Run test to verify it fails**

Run: `python -m pytest tests/test_db.py -x -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.core.db'`

- [ ] **Step 6: Implement core/db.py**

Create `backend/core/db.py`:

```python
"""SQLite metadata layer — connection, schema, and version management.

DB stores dataset registry, episode annotations (grade/tags), and
aggregated curation statistics. Actual episode/video data stays in
parquet files on NAS.
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from backend.core.config import settings

logger = logging.getLogger(__name__)

_connection: aiosqlite.Connection | None = None
_db_path_override: str | None = None  # for testing

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS datasets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    cell_name       TEXT,
    fps             INTEGER DEFAULT 0,
    total_episodes  INTEGER DEFAULT 0,
    robot_type      TEXT,
    features        TEXT,
    registered_at   TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    synced_at       TEXT
);

CREATE TABLE IF NOT EXISTS episode_annotations (
    dataset_id      INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    episode_index   INTEGER NOT NULL,
    grade           TEXT CHECK(grade IN ('good', 'normal', 'bad')),
    tags            TEXT DEFAULT '[]',
    updated_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (dataset_id, episode_index)
);

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
"""


def _get_db_path() -> Path:
    if _db_path_override:
        return Path(_db_path_override)
    if settings.db_path:
        return Path(settings.db_path)
    return Path.home() / ".local" / "share" / "curation-tools" / "metadata.db"


async def get_db() -> aiosqlite.Connection:
    """Return the singleton DB connection, creating it on first call."""
    global _connection
    if _connection is None:
        db_path = _get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _connection = await aiosqlite.connect(str(db_path))
        _connection.row_factory = aiosqlite.Row
        await _connection.execute("PRAGMA journal_mode=WAL")
        await _connection.execute("PRAGMA foreign_keys=ON")
    return _connection


async def init_db() -> None:
    """Create tables if needed and run version migrations."""
    db = await get_db()
    row = await db.execute_fetchone("PRAGMA user_version")
    version = row[0] if row else 0
    if version < 1:
        await db.executescript(SCHEMA_V1)
        await db.execute("PRAGMA user_version = 1")
        await db.commit()
        logger.info("Database initialized (v1) at %s", _get_db_path())


async def close_db() -> None:
    """Close the DB connection."""
    global _connection
    if _connection is not None:
        await _connection.close()
        _connection = None


def _reset() -> None:
    """Reset module state (for testing only)."""
    global _connection, _db_path_override
    _connection = None
    _db_path_override = None
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_db.py -x -v`
Expected: all tests PASS

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml backend/core/config.py backend/core/db.py tests/test_db.py
git commit -m "feat: add core/db.py — SQLite metadata layer with schema v1"
```

---

### Task 2: Wire init_db/close_db into main.py lifespan

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Update lifespan to init and close DB**

In `backend/main.py`, add imports and modify the lifespan function:

```python
from backend.core.db import init_db, close_db
```

Update the lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    if settings.enable_rerun:
        try:
            rerun_service.init_rerun(
                grpc_port=settings.rerun_grpc_port,
                web_port=settings.rerun_web_port,
            )
            logger.info("Rerun viewer available at http://localhost:%d", settings.rerun_web_port)
        except Exception as e:
            logger.warning("Rerun init failed: %s (video player still works)", e)
    else:
        logger.info("Rerun disabled — using native video player")

    yield

    await close_db()
```

- [ ] **Step 2: Verify app starts**

Run: `python -c "from backend.main import app; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: wire init_db/close_db into FastAPI lifespan"
```

---

### Task 3: Modify cell_service to upsert datasets into DB

**Files:**
- Modify: `backend/datasets/services/cell_service.py`
- Create: `tests/test_cell_service_db.py`

- [ ] **Step 1: Write failing test for DB upsert**

Create `tests/test_cell_service_db.py`:

```python
"""Tests for cell_service DB upsert — datasets are registered in SQLite on scan."""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from backend.core.db import get_db, init_db, close_db, _reset


@pytest.fixture(autouse=True)
async def tmp_db(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    await init_db()
    yield tmp
    await close_db()
    _reset()
    tmp.unlink(missing_ok=True)


@pytest.fixture
def mock_cell(tmp_path):
    """Create a fake cell with two datasets."""
    cell = tmp_path / "cell_a"
    cell.mkdir()
    for name, fps, episodes in [("ds1", 30, 10), ("ds2", 60, 5)]:
        ds = cell / name
        ds.mkdir()
        meta = ds / "meta"
        meta.mkdir()
        (meta / "info.json").write_text(json.dumps({
            "fps": fps, "total_episodes": episodes, "robot_type": "so100",
            "features": {"obs": {"dtype": "float"}},
        }))
        ep_dir = meta / "episodes" / "chunk-000"
        ep_dir.mkdir(parents=True)
    return cell


class TestGetDatasetsUpsert:
    @pytest.mark.asyncio
    async def test_datasets_inserted_into_db(self, mock_cell):
        from backend.datasets.services.cell_service import get_datasets_in_cell
        result = get_datasets_in_cell(str(mock_cell))
        assert len(result) == 2

        db = await get_db()
        rows = await db.execute_fetchall(
            "SELECT path, name, cell_name, fps FROM datasets ORDER BY name"
        )
        assert len(rows) == 2
        assert rows[0]["name"] == "ds1"
        assert rows[0]["fps"] == 30
        assert rows[0]["cell_name"] == "cell_a"

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self, mock_cell):
        from backend.datasets.services.cell_service import get_datasets_in_cell
        get_datasets_in_cell(str(mock_cell))
        # Change info and rescan
        info_path = mock_cell / "ds1" / "meta" / "info.json"
        info = json.loads(info_path.read_text())
        info["total_episodes"] = 99
        info_path.write_text(json.dumps(info))
        get_datasets_in_cell(str(mock_cell))

        db = await get_db()
        row = await db.execute_fetchone(
            "SELECT total_episodes FROM datasets WHERE name = 'ds1'"
        )
        assert row["total_episodes"] == 99
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cell_service_db.py -x -v`
Expected: FAIL — no DB upsert logic in cell_service yet

- [ ] **Step 3: Implement DB upsert in cell_service**

In `backend/datasets/services/cell_service.py`, add the DB upsert at the end of `get_datasets_in_cell()`.

Add import at top:

```python
import asyncio as _asyncio
```

Add helper function after imports:

```python
def _upsert_datasets_to_db(cell_name: str, datasets: list[DatasetSummary]) -> None:
    """Sync discovered datasets into SQLite (fire-and-forget from sync context)."""
    import json as _json
    from backend.core.db import get_db

    async def _do_upsert():
        db = await get_db()
        for ds in datasets:
            await db.execute(
                """INSERT INTO datasets (path, name, cell_name, fps, total_episodes, robot_type, synced_at)
                   VALUES (?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                   ON CONFLICT(path) DO UPDATE SET
                     name=excluded.name, cell_name=excluded.cell_name,
                     fps=excluded.fps, total_episodes=excluded.total_episodes,
                     robot_type=excluded.robot_type,
                     synced_at=excluded.synced_at""",
                (ds.path, ds.name, cell_name, ds.fps, ds.total_episodes, ds.robot_type),
            )
            # Upsert stats
            await db.execute(
                """INSERT INTO dataset_stats (dataset_id, graded_count, good_count, normal_count, bad_count,
                     total_duration_sec, good_duration_sec, normal_duration_sec, bad_duration_sec, updated_at)
                   SELECT id, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                   FROM datasets WHERE path = ?
                   ON CONFLICT(dataset_id) DO UPDATE SET
                     graded_count=excluded.graded_count, good_count=excluded.good_count,
                     normal_count=excluded.normal_count, bad_count=excluded.bad_count,
                     total_duration_sec=excluded.total_duration_sec,
                     good_duration_sec=excluded.good_duration_sec,
                     normal_duration_sec=excluded.normal_duration_sec,
                     bad_duration_sec=excluded.bad_duration_sec,
                     updated_at=excluded.updated_at""",
                (ds.graded_count, ds.good_count, ds.normal_count, ds.bad_count,
                 ds.total_duration_sec, ds.good_duration_sec, ds.normal_duration_sec, ds.bad_duration_sec,
                 ds.path),
            )
        await db.commit()

    try:
        loop = _asyncio.get_running_loop()
        loop.create_task(_do_upsert())
    except RuntimeError:
        _asyncio.run(_do_upsert())
```

At the end of `get_datasets_in_cell()`, before `return datasets`, add:

```python
    _upsert_datasets_to_db(root.name, datasets)
    return datasets
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cell_service_db.py -x -v`
Expected: PASS

- [ ] **Step 5: Run existing cell_service tests to check no regressions**

Run: `python -m pytest tests/test_cell_service.py -x -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/datasets/services/cell_service.py tests/test_cell_service_db.py
git commit -m "feat: cell_service upserts discovered datasets into SQLite"
```

---

### Task 4: Modify episode_service — annotations from DB + sidecar migration

**Files:**
- Modify: `backend/datasets/services/episode_service.py`
- Create: `tests/test_episode_annotations_db.py`

- [ ] **Step 1: Write failing test for DB annotation read/write**

Create `tests/test_episode_annotations_db.py`:

```python
"""Tests for episode annotation DB read/write and sidecar migration."""

import json
import tempfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.core.db import get_db, init_db, close_db, _reset


@pytest.fixture(autouse=True)
async def tmp_db(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    await init_db()
    yield tmp
    await close_db()
    _reset()
    tmp.unlink(missing_ok=True)


@pytest.fixture
def mock_dataset(tmp_path, monkeypatch):
    """Create a minimal dataset and register it in DB + dataset_service."""
    ds_path = tmp_path / "test_dataset"
    meta = ds_path / "meta"
    meta.mkdir(parents=True)
    (meta / "info.json").write_text(json.dumps({
        "fps": 30, "total_episodes": 3, "robot_type": "so100", "features": {},
    }))
    tasks_table = pa.table({"task_index": [0], "task": ["pick"]})
    pq.write_table(tasks_table, meta / "tasks.parquet")
    ep_dir = meta / "episodes" / "chunk-000"
    ep_dir.mkdir(parents=True)
    ep_table = pa.table({
        "episode_index": [0, 1, 2],
        "length": [100, 200, 150],
        "task_index": [0, 0, 0],
        "data/chunk_index": [0, 0, 0],
        "data/file_index": [0, 0, 0],
        "dataset_from_index": [0, 100, 300],
        "dataset_to_index": [100, 300, 450],
    })
    pq.write_table(ep_table, ep_dir / "file-000.parquet")

    # Register dataset in DB
    import asyncio
    async def _register():
        db = await get_db()
        await db.execute(
            "INSERT INTO datasets (path, name, fps, total_episodes) VALUES (?, ?, 30, 3)",
            (str(ds_path), "test_dataset"),
        )
        await db.commit()
    asyncio.get_event_loop().run_until_complete(_register())

    # Load into dataset_service
    from backend.core.config import settings
    original_roots = settings.allowed_dataset_roots
    settings.allowed_dataset_roots = original_roots + [str(tmp_path)]
    from backend.datasets.services.dataset_service import DatasetService
    svc = DatasetService()
    svc.load_dataset(str(ds_path))

    monkeypatch.setattr(
        "backend.datasets.services.episode_service.dataset_service", svc
    )
    yield ds_path
    settings.allowed_dataset_roots = original_roots


class TestAnnotationDbWrite:
    @pytest.mark.asyncio
    async def test_update_writes_to_db(self, mock_dataset):
        from backend.datasets.services.episode_service import EpisodeService
        svc = EpisodeService()
        await svc.update_episode(0, grade="good", tags=["clean"])

        db = await get_db()
        row = await db.execute_fetchone(
            "SELECT grade, tags FROM episode_annotations WHERE episode_index = 0"
        )
        assert row["grade"] == "good"
        assert json.loads(row["tags"]) == ["clean"]

    @pytest.mark.asyncio
    async def test_bulk_grade_writes_to_db(self, mock_dataset):
        from backend.datasets.services.episode_service import EpisodeService
        svc = EpisodeService()
        await svc.bulk_grade([0, 1, 2], "normal")

        db = await get_db()
        rows = await db.execute_fetchall(
            "SELECT episode_index, grade FROM episode_annotations ORDER BY episode_index"
        )
        assert len(rows) == 3
        assert all(r["grade"] == "normal" for r in rows)


class TestAnnotationDbRead:
    @pytest.mark.asyncio
    async def test_get_episodes_reads_from_db(self, mock_dataset):
        from backend.datasets.services.episode_service import EpisodeService
        svc = EpisodeService()
        # Write directly to DB
        db = await get_db()
        ds_row = await db.execute_fetchone("SELECT id FROM datasets WHERE name = 'test_dataset'")
        await db.execute(
            "INSERT INTO episode_annotations (dataset_id, episode_index, grade, tags) VALUES (?, 1, 'bad', ?)",
            (ds_row["id"], json.dumps(["damaged"])),
        )
        await db.commit()

        episodes = await svc.get_episodes()
        ep1 = next(e for e in episodes if e["episode_index"] == 1)
        assert ep1["grade"] == "bad"
        assert ep1["tags"] == ["damaged"]


class TestSidecarMigration:
    @pytest.mark.asyncio
    async def test_migrates_existing_sidecar_on_first_read(self, mock_dataset, tmp_path):
        from backend.datasets.services.episode_service import (
            EpisodeService, _sidecar_file,
        )
        # Write a sidecar JSON at the expected path
        sidecar_path = _sidecar_file(mock_dataset)
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(json.dumps({
            "0": {"grade": "good", "tags": ["migrated"]},
            "2": {"grade": "bad", "tags": []},
        }))

        svc = EpisodeService()
        episodes = await svc.get_episodes()

        # Check DB has the migrated data
        db = await get_db()
        rows = await db.execute_fetchall(
            "SELECT episode_index, grade FROM episode_annotations ORDER BY episode_index"
        )
        grades = {r["episode_index"]: r["grade"] for r in rows}
        assert grades[0] == "good"
        assert grades[2] == "bad"

        # Sidecar file should NOT be deleted
        assert sidecar_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_episode_annotations_db.py -x -v`
Expected: FAIL — episode_service still uses JSON sidecar

- [ ] **Step 3: Implement DB annotation logic in episode_service**

Modify `backend/datasets/services/episode_service.py`:

1. Rename `_load_sidecar` to `_load_sidecar_json` (keep for migration)
2. Keep `_sidecar_file` (used by migration and test)
3. Add DB-based annotation functions
4. Add `_ensure_migrated()` for automatic sidecar migration
5. Add `_get_dataset_id()` helper to look up dataset in DB
6. Add `_refresh_dataset_stats()` to recompute stats after grade changes
7. Update `get_episodes()`, `get_episode()`, `update_episode()`, `bulk_grade()` to use DB

Key changes to the class:

```python
import json as _json
from backend.core.db import get_db

async def _get_dataset_id(dataset_path: Path) -> int | None:
    """Look up dataset ID in the DB. Returns None if not registered."""
    db = await get_db()
    row = await db.execute_fetchone(
        "SELECT id FROM datasets WHERE path = ?", (str(dataset_path.resolve()),)
    )
    return row["id"] if row else None

async def _ensure_dataset_registered(dataset_path: Path) -> int:
    """Ensure dataset is in DB, insert if missing. Returns dataset ID."""
    db = await get_db()
    row = await db.execute_fetchone(
        "SELECT id FROM datasets WHERE path = ?", (str(dataset_path.resolve()),)
    )
    if row:
        return row["id"]
    await db.execute(
        "INSERT INTO datasets (path, name) VALUES (?, ?)",
        (str(dataset_path.resolve()), dataset_path.name),
    )
    await db.commit()
    row = await db.execute_fetchone(
        "SELECT id FROM datasets WHERE path = ?", (str(dataset_path.resolve()),)
    )
    return row["id"]

async def _ensure_migrated(dataset_id: int, dataset_path: Path) -> None:
    """Migrate JSON sidecar to DB on first access if needed."""
    db = await get_db()
    count = await db.execute_fetchone(
        "SELECT COUNT(*) as cnt FROM episode_annotations WHERE dataset_id = ?",
        (dataset_id,),
    )
    if count["cnt"] > 0:
        return  # already has annotations in DB

    sidecar = _load_sidecar_json(dataset_path)
    if not sidecar:
        return  # no JSON sidecar either

    await db.executemany(
        """INSERT OR IGNORE INTO episode_annotations (dataset_id, episode_index, grade, tags)
           VALUES (?, ?, ?, ?)""",
        [(dataset_id, int(idx), ann.get("grade"), _json.dumps(ann.get("tags", [])))
         for idx, ann in sidecar.items()],
    )
    await db.commit()
    await _refresh_dataset_stats(dataset_id)
    logger.info("Migrated %d annotations from sidecar for dataset %s", len(sidecar), dataset_path.name)

async def _load_annotations_from_db(dataset_id: int) -> dict[int, dict]:
    """Load all annotations for a dataset from DB. Returns {episode_index: {grade, tags}}."""
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT episode_index, grade, tags FROM episode_annotations WHERE dataset_id = ?",
        (dataset_id,),
    )
    return {
        row["episode_index"]: {
            "grade": row["grade"],
            "tags": _json.loads(row["tags"]) if row["tags"] else [],
        }
        for row in rows
    }

async def _save_annotation_to_db(dataset_id: int, episode_index: int, grade: str | None, tags: list[str]) -> None:
    """Write a single annotation to DB."""
    db = await get_db()
    await db.execute(
        """INSERT INTO episode_annotations (dataset_id, episode_index, grade, tags, updated_at)
           VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
           ON CONFLICT(dataset_id, episode_index) DO UPDATE SET
             grade=excluded.grade, tags=excluded.tags, updated_at=excluded.updated_at""",
        (dataset_id, episode_index, grade, _json.dumps(tags)),
    )
    await db.commit()

async def _refresh_dataset_stats(dataset_id: int) -> None:
    """Recompute dataset_stats from episode_annotations."""
    db = await get_db()
    await db.execute(
        """INSERT INTO dataset_stats (dataset_id, graded_count, good_count, normal_count, bad_count, updated_at)
           SELECT
             ?,
             COUNT(grade),
             SUM(CASE WHEN grade='good' THEN 1 ELSE 0 END),
             SUM(CASE WHEN grade='normal' THEN 1 ELSE 0 END),
             SUM(CASE WHEN grade='bad' THEN 1 ELSE 0 END),
             strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
           FROM episode_annotations WHERE dataset_id = ?
           ON CONFLICT(dataset_id) DO UPDATE SET
             graded_count=excluded.graded_count, good_count=excluded.good_count,
             normal_count=excluded.normal_count, bad_count=excluded.bad_count,
             updated_at=excluded.updated_at""",
        (dataset_id, dataset_id),
    )
    await db.commit()
```

Update `EpisodeService.get_episodes()` — after building episodes from parquet, merge annotations from DB instead of sidecar:

```python
async def get_episodes(self) -> list[dict[str, Any]]:
    if dataset_service.episodes_cache is not None:
        return list(dataset_service.episodes_cache.values())

    episodes: dict[int, dict[str, Any]] = {}
    tasks_map = await dataset_service.get_tasks_map()

    # DB annotation merge instead of sidecar
    dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
    await _ensure_migrated(dataset_id, dataset_service.dataset_path)
    annotations = await _load_annotations_from_db(dataset_id)

    for file_path in dataset_service.iter_episode_parquet_files():
        table = await asyncio.to_thread(pq.read_table, file_path)
        for row in _iter_rows(table):
            ep = _row_to_episode(row, tasks_map)
            ann = annotations.get(ep["episode_index"])
            if ann:
                ep["grade"] = ann.get("grade")
                ep["tags"] = ann.get("tags", [])
            episodes[ep["episode_index"]] = ep

    dataset_service.episodes_cache = episodes
    return list(episodes.values())
```

Update `update_episode()` — write to DB instead of sidecar:

```python
async def update_episode(self, episode_index: int, grade: str | None, tags: list[str]) -> dict[str, Any]:
    # Verify episode exists (same logic as before)
    if dataset_service.episodes_cache is not None:
        if episode_index not in dataset_service.episodes_cache:
            raise EpisodeNotFoundError(f"Episode {episode_index} not found.")
    else:
        file_path = dataset_service.get_file_for_episode(episode_index)
        if file_path is None:
            raise EpisodeNotFoundError(f"Episode {episode_index} not found.")

    dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
    await _save_annotation_to_db(dataset_id, episode_index, grade, tags)
    await _refresh_dataset_stats(dataset_id)

    # Invalidate distribution cache
    dataset_service.distribution_cache.pop("grade:auto", None)
    dataset_service.distribution_cache.pop("grade:bar", None)
    dataset_service.distribution_cache.pop("tags:auto", None)
    dataset_service.distribution_cache.pop("tags:bar", None)

    # Update in-memory cache
    if dataset_service.episodes_cache is not None:
        ep = dataset_service.episodes_cache.get(episode_index)
        if ep:
            ep["grade"] = grade
            ep["tags"] = tags
            return ep

    return await self.get_episode(episode_index)
```

Update `bulk_grade()` — same pattern, write to DB:

```python
async def bulk_grade(self, episode_indices: list[int], grade: str) -> int:
    dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
    db = await get_db()
    for idx in episode_indices:
        # Get existing tags to preserve them
        existing = await db.execute_fetchone(
            "SELECT tags FROM episode_annotations WHERE dataset_id = ? AND episode_index = ?",
            (dataset_id, idx),
        )
        tags_json = existing["tags"] if existing else "[]"
        await db.execute(
            """INSERT INTO episode_annotations (dataset_id, episode_index, grade, tags, updated_at)
               VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
               ON CONFLICT(dataset_id, episode_index) DO UPDATE SET
                 grade=excluded.grade, updated_at=excluded.updated_at""",
            (dataset_id, idx, grade, tags_json),
        )
    await db.commit()
    await _refresh_dataset_stats(dataset_id)

    # Invalidate distribution cache
    dataset_service.distribution_cache.pop("grade:auto", None)
    dataset_service.distribution_cache.pop("grade:bar", None)
    dataset_service.distribution_cache.pop("tags:auto", None)
    dataset_service.distribution_cache.pop("tags:bar", None)

    # Update in-memory cache
    if dataset_service.episodes_cache is not None:
        for idx in episode_indices:
            ep = dataset_service.episodes_cache.get(idx)
            if ep:
                ep["grade"] = grade

    return len(episode_indices)
```

Update `get_episode()` — read single annotation from DB:

```python
async def get_episode(self, episode_index: int) -> dict[str, Any]:
    if dataset_service.episodes_cache is not None:
        try:
            return dataset_service.episodes_cache[episode_index]
        except KeyError:
            raise EpisodeNotFoundError(f"Episode {episode_index} not found in cache.")

    tasks_map = await dataset_service.get_tasks_map()
    file_path = dataset_service.get_file_for_episode(episode_index)
    if file_path is None:
        raise EpisodeNotFoundError(f"Episode {episode_index} not found in any parquet file.")

    table = await asyncio.to_thread(pq.read_table, file_path)
    dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
    await _ensure_migrated(dataset_id, dataset_service.dataset_path)

    db = await get_db()
    ann_row = await db.execute_fetchone(
        "SELECT grade, tags FROM episode_annotations WHERE dataset_id = ? AND episode_index = ?",
        (dataset_id, episode_index),
    )

    for row in _iter_rows(table):
        if row.get("episode_index") == episode_index:
            ep = _row_to_episode(row, tasks_map)
            if ann_row:
                ep["grade"] = ann_row["grade"]
                ep["tags"] = _json.loads(ann_row["tags"]) if ann_row["tags"] else []
            return ep

    raise EpisodeNotFoundError(f"Episode {episode_index} not found in {file_path}.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_episode_annotations_db.py -x -v`
Expected: PASS

- [ ] **Step 5: Run existing episode tests**

Run: `python -m pytest tests/test_mockup.py -x -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/datasets/services/episode_service.py tests/test_episode_annotations_db.py
git commit -m "feat: episode annotations stored in SQLite, auto-migrate from JSON sidecar"
```

---

### Task 5: Update export_service to read grades from DB

**Files:**
- Modify: `backend/datasets/services/export_service.py`

- [ ] **Step 1: Update export_service to use DB annotations**

In `backend/datasets/services/export_service.py`, replace the sidecar import and usage:

Remove:
```python
from backend.datasets.services.episode_service import _load_sidecar
```

Add:
```python
from backend.datasets.services.episode_service import (
    _ensure_dataset_registered, _ensure_migrated, _load_annotations_from_db,
)
```

In `export_dataset()`, replace the sidecar reading section:

```python
# Old code:
# sidecar = _load_sidecar(ds_path)
# episode_grades: dict[int, str | None] = {}
# for ep in episodes:
#     ep_idx = ep["episode_index"]
#     episode_grades[ep_idx] = ep.get("grade")
# for ep_idx_str, ann in sidecar.items():
#     grade = ann.get("grade")
#     if grade is not None:
#         episode_grades[int(ep_idx_str)] = grade

# New code:
import asyncio
dataset_id = asyncio.get_event_loop().run_until_complete(
    _ensure_dataset_registered(ds_path)
)
asyncio.get_event_loop().run_until_complete(
    _ensure_migrated(dataset_id, ds_path)
)
annotations = asyncio.get_event_loop().run_until_complete(
    _load_annotations_from_db(dataset_id)
)
episode_grades: dict[int, str | None] = {}
for ep in episodes:
    ep_idx = ep["episode_index"]
    episode_grades[ep_idx] = ep.get("grade")
for ep_idx, ann in annotations.items():
    grade = ann.get("grade")
    if grade is not None:
        episode_grades[ep_idx] = grade
```

Note: `export_dataset()` is a sync function. Use `asyncio.get_event_loop().run_until_complete()` to call async DB functions. This is safe because it's called from within a running FastAPI event loop context.

- [ ] **Step 2: Run existing export tests**

Run: `python -m pytest tests/test_mockup.py::TestExportDataset -x -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/datasets/services/export_service.py
git commit -m "feat: export_service reads grades from SQLite instead of JSON sidecar"
```

---

### Task 6: Update distribution_service annotation reading

**Files:**
- Modify: `backend/datasets/services/distribution_service.py`

- [ ] **Step 1: Update _compute_annotation_distribution to use DB**

In `backend/datasets/services/distribution_service.py`, update the `_compute_annotation_distribution()` function.

Replace the lazy sidecar import:
```python
# Old:
from backend.datasets.services.episode_service import _load_sidecar
```

With DB import:
```python
from backend.datasets.services.episode_service import (
    _ensure_dataset_registered, _ensure_migrated, _load_annotations_from_db,
)
```

Replace the sidecar reading section in `_compute_annotation_distribution()` with DB reading:

```python
import asyncio

dataset_path_obj = Path(dataset_path)

# Get annotations from DB instead of sidecar
dataset_id = asyncio.get_event_loop().run_until_complete(
    _ensure_dataset_registered(dataset_path_obj)
)
asyncio.get_event_loop().run_until_complete(
    _ensure_migrated(dataset_id, dataset_path_obj)
)
db_annotations = asyncio.get_event_loop().run_until_complete(
    _load_annotations_from_db(dataset_id)
)
```

Then replace the sidecar overlay section — instead of reading from parquet + sidecar, read from parquet + DB annotations. The `db_annotations` dict has the same structure as the sidecar dict, so the rest of the function works with minimal changes:

```python
# Read base from parquet (unchanged)
# ...existing parquet reading code...

# Overlay DB annotations (replaces sidecar overlay)
for ep_idx, ann in db_annotations.items():
    if ep_idx in episodes:
        if ann.get("grade") is not None:
            episodes[ep_idx]["grade"] = ann["grade"]
        if ann.get("tags") is not None:
            episodes[ep_idx]["tags"] = ann["tags"]
    else:
        episodes[ep_idx] = {
            "grade": ann.get("grade"),
            "tags": ann.get("tags", []),
        }
```

- [ ] **Step 2: Run distribution tests**

Run: `python -m pytest tests/test_distribution_service.py -x -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/datasets/services/distribution_service.py
git commit -m "feat: distribution_service reads annotations from SQLite"
```

---

### Task 7: Update cell_service _count_grades to use DB

**Files:**
- Modify: `backend/datasets/services/cell_service.py`

- [ ] **Step 1: Update _count_grades to try DB first**

In `_count_grades()`, try reading from `dataset_stats` table first. Fall back to parquet+sidecar scan if dataset is not in DB yet.

```python
def _count_grades(dataset_dir: Path, fps: int = 0) -> dict[str, int | float]:
    """Count grades and durations. Uses DB stats if available, falls back to parquet scan."""
    import asyncio

    # Try DB first
    try:
        from backend.core.db import get_db

        async def _from_db():
            db = await get_db()
            row = await db.execute_fetchone(
                """SELECT ds.graded_count, ds.good_count, ds.normal_count, ds.bad_count,
                          ds.total_duration_sec, ds.good_duration_sec,
                          ds.normal_duration_sec, ds.bad_duration_sec
                   FROM dataset_stats ds
                   JOIN datasets d ON ds.dataset_id = d.id
                   WHERE d.path = ?""",
                (str(dataset_dir.resolve()),),
            )
            return row

        loop = asyncio.get_event_loop()
        row = loop.run_until_complete(_from_db())
        if row and row["graded_count"] > 0:
            return {
                "good": row["good_count"], "normal": row["normal_count"], "bad": row["bad_count"],
                "total_duration_sec": row["total_duration_sec"],
                "good_duration_sec": row["good_duration_sec"],
                "normal_duration_sec": row["normal_duration_sec"],
                "bad_duration_sec": row["bad_duration_sec"],
            }
    except Exception:
        pass  # DB not initialized or not available — fall back

    # Fall back to parquet + sidecar scan (existing logic)
    from glob import glob
    import pyarrow.parquet as pq
    from backend.datasets.services.episode_service import _load_sidecar_json
    # ... rest of existing _count_grades logic, using _load_sidecar_json instead of _load_sidecar ...
```

Update the fallback to call `_load_sidecar_json` instead of `_load_sidecar`:

```python
    sidecar = _load_sidecar_json(dataset_dir)
```

- [ ] **Step 2: Run cell_service tests**

Run: `python -m pytest tests/test_cell_service.py tests/test_cell_service_db.py -x -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/datasets/services/cell_service.py
git commit -m "feat: cell_service reads stats from DB, falls back to parquet scan"
```

---

### Task 8: Add cross-dataset search endpoint

**Files:**
- Modify: `backend/datasets/routers/datasets.py`
- Create: `tests/test_dataset_search.py`

- [ ] **Step 1: Write failing test for search endpoint**

Create `tests/test_dataset_search.py`:

```python
"""Tests for GET /api/datasets/search — cross-dataset search via SQLite."""

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from backend.core.db import get_db, init_db, close_db, _reset
from backend.main import app


@pytest.fixture(autouse=True)
async def tmp_db(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    await init_db()
    # Seed test data
    db = await get_db()
    for i, (name, cell, robot, fps, episodes) in enumerate([
        ("ds_good", "cell_a", "so100", 30, 100),
        ("ds_mixed", "cell_a", "so100", 30, 50),
        ("ds_small", "cell_b", "koch", 60, 5),
    ], start=1):
        await db.execute(
            "INSERT INTO datasets (id, path, name, cell_name, robot_type, fps, total_episodes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (i, f"/mnt/nas/{cell}/{name}", name, cell, robot, fps, episodes),
        )
        good = {1: 80, 2: 20, 3: 3}[i]
        normal = {1: 10, 2: 10, 3: 1}[i]
        bad = {1: 10, 2: 20, 3: 1}[i]
        await db.execute(
            """INSERT INTO dataset_stats (dataset_id, graded_count, good_count, normal_count, bad_count)
               VALUES (?, ?, ?, ?, ?)""",
            (i, good + normal + bad, good, normal, bad),
        )
    await db.commit()
    yield tmp
    await close_db()
    _reset()
    tmp.unlink(missing_ok=True)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestDatasetSearch:
    @pytest.mark.asyncio
    async def test_no_filters_returns_all(self, client):
        resp = await client.get("/api/datasets/search")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    @pytest.mark.asyncio
    async def test_filter_by_robot_type(self, client):
        resp = await client.get("/api/datasets/search?robot_type=so100")
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()]
        assert "ds_good" in names
        assert "ds_mixed" in names
        assert "ds_small" not in names

    @pytest.mark.asyncio
    async def test_filter_by_cell(self, client):
        resp = await client.get("/api/datasets/search?cell=cell_b")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "ds_small"

    @pytest.mark.asyncio
    async def test_filter_by_min_good_ratio(self, client):
        resp = await client.get("/api/datasets/search?min_good_ratio=0.7")
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()]
        assert "ds_good" in names  # 80/100 = 0.8
        assert "ds_mixed" not in names  # 20/50 = 0.4

    @pytest.mark.asyncio
    async def test_filter_by_min_episodes(self, client):
        resp = await client.get("/api/datasets/search?min_episodes=10")
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()]
        assert "ds_small" not in names  # only 5 episodes

    @pytest.mark.asyncio
    async def test_combined_filters(self, client):
        resp = await client.get("/api/datasets/search?robot_type=so100&min_good_ratio=0.5")
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()]
        assert names == ["ds_good"]  # so100 + ratio > 0.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dataset_search.py -x -v`
Expected: FAIL — 404, endpoint doesn't exist

- [ ] **Step 3: Add search endpoint to datasets router**

In `backend/datasets/routers/datasets.py`, add:

```python
from backend.core.db import get_db


@router.get("/search")
async def search_datasets(
    robot_type: str | None = Query(None),
    cell: str | None = Query(None),
    min_episodes: int | None = Query(None),
    min_good_ratio: float | None = Query(None),
):
    """Search across all registered datasets using DB metadata."""
    db = await get_db()
    query = """
        SELECT d.name, d.path, d.cell_name, d.robot_type, d.fps, d.total_episodes,
               COALESCE(s.graded_count, 0) as graded_count,
               COALESCE(s.good_count, 0) as good_count,
               COALESCE(s.normal_count, 0) as normal_count,
               COALESCE(s.bad_count, 0) as bad_count,
               COALESCE(s.total_duration_sec, 0) as total_duration_sec,
               COALESCE(s.good_duration_sec, 0) as good_duration_sec,
               COALESCE(s.normal_duration_sec, 0) as normal_duration_sec,
               COALESCE(s.bad_duration_sec, 0) as bad_duration_sec
        FROM datasets d
        LEFT JOIN dataset_stats s ON d.id = s.dataset_id
        WHERE 1=1
    """
    params: list = []

    if robot_type is not None:
        query += " AND d.robot_type = ?"
        params.append(robot_type)
    if cell is not None:
        query += " AND d.cell_name = ?"
        params.append(cell)
    if min_episodes is not None:
        query += " AND d.total_episodes >= ?"
        params.append(min_episodes)
    if min_good_ratio is not None:
        query += " AND CASE WHEN s.graded_count > 0 THEN CAST(s.good_count AS REAL) / s.graded_count ELSE 0 END >= ?"
        params.append(min_good_ratio)

    query += " ORDER BY d.name"

    rows = await db.execute_fetchall(query, params)
    return [
        {
            "name": r["name"],
            "path": r["path"],
            "total_episodes": r["total_episodes"],
            "graded_count": r["graded_count"],
            "good_count": r["good_count"],
            "normal_count": r["normal_count"],
            "bad_count": r["bad_count"],
            "robot_type": r["robot_type"],
            "fps": r["fps"],
            "total_duration_sec": r["total_duration_sec"],
            "good_duration_sec": r["good_duration_sec"],
            "normal_duration_sec": r["normal_duration_sec"],
            "bad_duration_sec": r["bad_duration_sec"],
        }
        for r in rows
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dataset_search.py -x -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/routers/datasets.py tests/test_dataset_search.py
git commit -m "feat: add GET /api/datasets/search — cross-dataset search via SQLite"
```

---

### Task 9: Update shim files and run full test suite

**Files:**
- Modify: `backend/services/episode_service.py` (shim)
- Modify: `backend/services/cell_service.py` (shim)

- [ ] **Step 1: Update episode_service shim to re-export new functions**

In `backend/services/episode_service.py`, add the new DB functions to explicit re-exports:

```python
"""Backwards-compatibility shim — import from backend.datasets.services.episode_service instead."""
from backend.datasets.services.episode_service import *  # noqa: F401, F403
from backend.datasets.services.episode_service import (  # noqa: F401
    EpisodeNotFoundError, EpisodeService, episode_service,
    _load_sidecar_json, _sidecar_file,
    _ensure_dataset_registered, _ensure_migrated, _load_annotations_from_db,
    _save_annotation_to_db, _refresh_dataset_stats, _get_dataset_id,
)
```

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest tests/ --ignore=tests/test_e2e.py --tb=short -q`
Expected: All mock-based tests PASS. Data-dependent tests may fail (pre-existing, not related to this change).

- [ ] **Step 3: Commit**

```bash
git add backend/services/episode_service.py backend/services/cell_service.py
git commit -m "chore: update shims for new DB functions"
```

---

## Self-Review

### Spec Coverage

| Spec Requirement | Task |
|---|---|
| core/db.py — connection, schema, versioning | Task 1 |
| config.py — db_path setting | Task 1 |
| main.py — lifespan init/close | Task 2 |
| cell_service — DB upsert on scan | Task 3 |
| episode_service — DB annotations + sidecar migration | Task 4 |
| export_service — read grades from DB | Task 5 |
| distribution_service — read annotations from DB | Task 6 |
| cell_service — _count_grades from DB | Task 7 |
| Cross-dataset search endpoint | Task 8 |
| Shim updates + regression testing | Task 9 |
| aiosqlite dependency | Task 1 |

### No Gaps Found

All spec sections have corresponding tasks. No placeholders or TBDs.
