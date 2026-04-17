# Grade Reason Capture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require a written reason when a curator marks an episode `bad` or `normal`. Persist the reason in SQLite only — never write it into parquet.

**Architecture:** Add `reason TEXT` column to `episode_annotations` (DB migration v1 → v2). Extend backend schemas/services/routers to round-trip `reason`. Frontend gains a shared `GradeReasonModal` triggered by both single-episode grade actions (button + `1`/`2`/`3` shortcut) and bulk "Mark as Bad". Auto-jump to next ungraded episode happens after the modal saves. Switching to `good` clears the reason.

**Tech Stack:** FastAPI + Pydantic v2 + aiosqlite (backend), React 19 + TypeScript + Vite + Axios (frontend), pytest + pytest-asyncio (tests).

**Spec:** `docs/superpowers/specs/2026-04-17-grade-reason-design.md`

---

## File Structure

**Modify:**
- `backend/core/db.py` — add `SCHEMA_V2` migration that adds `reason` column
- `backend/datasets/schemas.py` — extend `Episode`, `EpisodeUpdate`, `BulkGradeRequest`
- `backend/datasets/services/episode_service.py` — thread `reason` through DB load/save and bulk-grade
- `backend/datasets/routers/episodes.py` — forward `reason` from request to service
- `frontend/src/types/index.ts` — extend `Episode` and `EpisodeUpdate` with `reason`
- `frontend/src/hooks/useEpisodes.ts` — extend `updateEpisode` signature to accept `reason`
- `frontend/src/components/DatasetPage.tsx` — add `GradeReasonModal` state, route grade entry through it, render reason
- `frontend/src/components/OverviewTab.tsx` — open modal before posting bulk-grade
- `frontend/src/App.css` — modal styles

**Create:**
- `frontend/src/components/GradeReasonModal.tsx` — shared modal (single + bulk)
- `tests/test_grade_reason.py` — backend behavior + migration tests

Each file has a single responsibility. The modal is its own component because it is reused in two places.

---

## Conventions

- Backend tests use the existing `tmp_db` fixture pattern from `tests/test_db.py` (calls `_reset()` and `_db_path_override`).
- Backend service layer raises `ValueError` for input validation problems; routers convert to `HTTPException(400)`. Pydantic field validators surface as `422` automatically.
- Frontend keyboard shortcuts for grades are `1` (good), `2` (normal), `3` (bad) — mapping defined at `frontend/src/components/DatasetPage.tsx:21` (`GRADE_KEYS`). Do **not** invent new keys.
- API method for updating a single episode is **PATCH** `/api/episodes/{idx}` (see `backend/datasets/routers/episodes.py:27`).
- All frontend colors come from CSS variables (`var(--c-red)`, `var(--c-yellow)`, `var(--text-dim)`, etc.). Never hardcode hex.

---

## Task 1: DB migration to v2 (add `reason` column)

**Files:**
- Modify: `backend/core/db.py`
- Test: `tests/test_grade_reason.py` (new)

- [ ] **Step 1: Write the failing migration test**

Create `tests/test_grade_reason.py` with:

```python
"""Tests for grade-reason feature: DB migration, service, router."""

import tempfile
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from backend.core.db import _reset, close_db, get_db, init_db


@pytest_asyncio.fixture(autouse=True)
async def tmp_db(monkeypatch):
    _reset()
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    yield tmp
    await close_db()
    _reset()
    tmp.unlink(missing_ok=True)


class TestMigrationV2:
    @pytest.mark.asyncio
    async def test_fresh_init_has_reason_column(self, tmp_db):
        await init_db()
        db = await get_db()
        async with db.execute("PRAGMA table_info(episode_annotations)") as cursor:
            rows = await cursor.fetchall()
        col_names = [r[1] for r in rows]
        assert "reason" in col_names

    @pytest.mark.asyncio
    async def test_user_version_is_2(self, tmp_db):
        await init_db()
        db = await get_db()
        async with db.execute("PRAGMA user_version") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 2

    @pytest.mark.asyncio
    async def test_v1_db_upgrades_in_place(self, tmp_db):
        # Build a v1 DB by hand
        async with aiosqlite.connect(str(tmp_db)) as conn:
            await conn.executescript("""
                CREATE TABLE datasets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL
                );
                CREATE TABLE episode_annotations (
                    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    episode_index INTEGER NOT NULL,
                    grade TEXT CHECK(grade IN ('good','normal','bad')),
                    tags TEXT DEFAULT '[]',
                    updated_at TEXT,
                    PRIMARY KEY (dataset_id, episode_index)
                );
                CREATE TABLE dataset_stats (dataset_id INTEGER PRIMARY KEY);
                INSERT INTO datasets (path, name) VALUES ('/tmp/x', 'x');
                INSERT INTO episode_annotations (dataset_id, episode_index, grade, tags)
                VALUES (1, 0, 'bad', '[]');
                PRAGMA user_version = 1;
            """)
            await conn.commit()

        # Now run init_db — it should upgrade
        await init_db()
        db = await get_db()
        async with db.execute("PRAGMA user_version") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 2
        async with db.execute("PRAGMA table_info(episode_annotations)") as cursor:
            rows = await cursor.fetchall()
        assert "reason" in [r[1] for r in rows]
        # Pre-existing row preserved with NULL reason
        async with db.execute(
            "SELECT grade, reason FROM episode_annotations WHERE dataset_id=1 AND episode_index=0"
        ) as cursor:
            row = await cursor.fetchone()
        assert row[0] == "bad"
        assert row[1] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_grade_reason.py::TestMigrationV2 -v`
Expected: FAIL — `reason` column missing, version stuck at 1.

- [ ] **Step 3: Add migration to `backend/core/db.py`**

In `backend/core/db.py`, add the `SCHEMA_V2` constant after `SCHEMA_V1` and update `init_db()`:

```python
SCHEMA_V2 = """
ALTER TABLE episode_annotations ADD COLUMN reason TEXT;
"""


async def init_db() -> None:
    """Create tables if needed and run version migrations."""
    db = await get_db()
    async with db.execute("PRAGMA user_version") as cursor:
        row = await cursor.fetchone()
    version = row[0] if row else 0
    if version < 1:
        await db.executescript(SCHEMA_V1)
        await db.execute("PRAGMA user_version = 1")
        await db.commit()
        logger.info("Database initialized (v1) at %s", _get_db_path())
        version = 1
    if version < 2:
        await db.executescript(SCHEMA_V2)
        await db.execute("PRAGMA user_version = 2")
        await db.commit()
        logger.info("Database upgraded to v2 (reason column) at %s", _get_db_path())
```

Replace the existing `init_db()` function entirely with the version above.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_grade_reason.py::TestMigrationV2 -v`
Expected: PASS (3 tests).

Also run the existing v1 tests to make sure nothing broke:

Run: `pytest tests/test_db.py -v`
Expected: All existing tests still PASS. (`test_sets_user_version` may fail because it asserts `row[0] == 1`. If so, update it to `row[0] == 2` — version is bumped now.)

- [ ] **Step 5: Commit**

```bash
git add backend/core/db.py tests/test_grade_reason.py tests/test_db.py
git commit -m "feat(db): add reason column to episode_annotations (v2 migration)"
```

---

## Task 2: Extend Pydantic schemas with `reason`

**Files:**
- Modify: `backend/datasets/schemas.py`
- Test: `tests/test_grade_reason.py`

- [ ] **Step 1: Write the failing schema test**

Append to `tests/test_grade_reason.py`:

```python
class TestSchemas:
    def test_episode_response_includes_reason(self):
        from backend.datasets.schemas import Episode
        ep = Episode(
            episode_index=0, length=100, task_index=0,
            dataset_from_index=0, dataset_to_index=100,
            grade="bad", reason="camera shake",
        )
        assert ep.reason == "camera shake"
        assert ep.model_dump()["reason"] == "camera shake"

    def test_episode_response_default_reason_is_none(self):
        from backend.datasets.schemas import Episode
        ep = Episode(episode_index=0, length=0, task_index=0)
        assert ep.reason is None

    def test_update_requires_reason_for_bad(self):
        from pydantic import ValidationError

        from backend.datasets.schemas import EpisodeUpdate
        with pytest.raises(ValidationError):
            EpisodeUpdate(grade="bad", tags=[])
        with pytest.raises(ValidationError):
            EpisodeUpdate(grade="bad", tags=[], reason="   ")
        # Non-empty reason is fine
        EpisodeUpdate(grade="bad", tags=[], reason="too dark")

    def test_update_requires_reason_for_normal(self):
        from pydantic import ValidationError

        from backend.datasets.schemas import EpisodeUpdate
        with pytest.raises(ValidationError):
            EpisodeUpdate(grade="normal", tags=[])
        EpisodeUpdate(grade="normal", tags=[], reason="acceptable but slow")

    def test_update_good_does_not_require_reason(self):
        from backend.datasets.schemas import EpisodeUpdate
        u = EpisodeUpdate(grade="good", tags=[])
        assert u.reason is None

    def test_update_good_clears_reason_when_provided(self):
        # Reason supplied with grade=good should be allowed but ignored downstream;
        # at the schema level we accept it (service layer will null it out).
        from backend.datasets.schemas import EpisodeUpdate
        u = EpisodeUpdate(grade="good", tags=[], reason="ignored")
        assert u.grade == "good"

    def test_bulk_grade_requires_reason_for_bad(self):
        from pydantic import ValidationError

        from backend.datasets.schemas import BulkGradeRequest
        with pytest.raises(ValidationError):
            BulkGradeRequest(episode_indices=[0, 1], grade="bad")
        BulkGradeRequest(episode_indices=[0, 1], grade="bad", reason="bad batch")

    def test_bulk_grade_good_does_not_require_reason(self):
        from backend.datasets.schemas import BulkGradeRequest
        BulkGradeRequest(episode_indices=[0], grade="good")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_grade_reason.py::TestSchemas -v`
Expected: FAIL — `Episode` has no `reason`, validators don't enforce reason for bad/normal.

- [ ] **Step 3: Edit `backend/datasets/schemas.py`**

Add `reason` field to `Episode` (around line 14):

```python
class Episode(BaseModel):
    episode_index: int
    length: int
    task_index: int
    task_instruction: str = ""
    chunk_index: int = 0
    file_index: int = 0
    dataset_from_index: int = 0
    dataset_to_index: int = 0
    grade: str | None = None
    tags: list[str] = []
    reason: str | None = None
    created_at: str | None = None
```

Replace `EpisodeUpdate` with:

```python
class EpisodeUpdate(BaseModel):
    grade: str | None = None
    tags: list[str] | None = None
    reason: str | None = None

    @field_validator("grade")
    @classmethod
    def validate_grade(cls, v: str | None) -> str | None:
        if v is not None and v not in ("good", "normal", "bad"):
            raise ValueError("Grade must be one of: Good, Normal, Bad")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            v = [t.strip() for t in v if t.strip()]
        return v

    @model_validator(mode="after")
    def _reason_required_for_bad_or_normal(self):
        if self.grade in ("bad", "normal"):
            if self.reason is None or not self.reason.strip():
                raise ValueError("reason is required when grade is 'bad' or 'normal'")
        return self
```

Replace `BulkGradeRequest` with:

```python
class BulkGradeRequest(BaseModel):
    episode_indices: list[int]
    grade: str
    reason: str | None = None

    @field_validator("grade")
    @classmethod
    def validate_grade(cls, v: str) -> str:
        if v not in ("good", "normal", "bad"):
            raise ValueError("Grade must be one of: good, normal, bad")
        return v

    @model_validator(mode="after")
    def _reason_required_for_bad_or_normal(self):
        if self.grade in ("bad", "normal"):
            if self.reason is None or not self.reason.strip():
                raise ValueError("reason is required when grade is 'bad' or 'normal'")
        return self
```

At the top of the file, change the import line to:

```python
from pydantic import BaseModel, field_validator, model_validator
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_grade_reason.py::TestSchemas -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/schemas.py tests/test_grade_reason.py
git commit -m "feat(schemas): require reason when grade is bad or normal"
```

---

## Task 3: Persist `reason` in `episode_service`

**Files:**
- Modify: `backend/datasets/services/episode_service.py`
- Test: `tests/test_grade_reason.py`

- [ ] **Step 1: Write the failing service test**

Append to `tests/test_grade_reason.py`. Reuse the dataset helper pattern from `tests/test_episode_annotations_db.py`:

```python
import json as _json

import pyarrow as pa
import pyarrow.parquet as pq


def _create_mock_dataset(root: Path) -> Path:
    ds = root / "mock_ds"
    (ds / "meta" / "episodes" / "chunk-000").mkdir(parents=True, exist_ok=True)
    (ds / "data" / "chunk-000").mkdir(parents=True, exist_ok=True)
    (ds / "meta" / "info.json").write_text(_json.dumps({
        "fps": 30, "total_episodes": 3, "total_tasks": 1,
        "robot_type": "test_robot", "features": {},
    }))
    pq.write_table(
        pa.table({
            "task_index": pa.array([0], type=pa.int64()),
            "task": pa.array(["test"], type=pa.string()),
        }),
        ds / "meta" / "tasks.parquet",
    )
    pq.write_table(
        pa.table({
            "episode_index": pa.array([0, 1, 2], type=pa.int64()),
            "task_index": pa.array([0, 0, 0], type=pa.int64()),
            "data/chunk_index": pa.array([0, 0, 0], type=pa.int64()),
            "data/file_index": pa.array([0, 0, 0], type=pa.int64()),
            "dataset_from_index": pa.array([0, 100, 200], type=pa.int64()),
            "dataset_to_index": pa.array([100, 200, 300], type=pa.int64()),
        }),
        ds / "meta" / "episodes" / "chunk-000" / "file-000.parquet",
    )
    pq.write_table(
        pa.table({
            "episode_index": pa.array([0, 1, 2], type=pa.int64()),
            "timestamp": pa.array([0.0, 0.0, 0.0], type=pa.float32()),
        }),
        ds / "data" / "chunk-000" / "file-000.parquet",
    )
    return ds


@pytest_asyncio.fixture
async def loaded_service(tmp_db, tmp_path):
    """Create a fresh EpisodeService pointing at a mock dataset."""
    from backend.core.config import settings
    from backend.datasets.services.dataset_service import DatasetService
    from backend.datasets.services.episode_service import EpisodeService

    ds_path = _create_mock_dataset(tmp_path)
    original_roots = settings.allowed_dataset_roots
    if str(ds_path.parent) not in original_roots:
        settings.allowed_dataset_roots = original_roots + [str(ds_path.parent)]

    # Replace module-level singletons
    import backend.datasets.services.dataset_service as ds_mod
    import backend.datasets.services.episode_service as ep_mod
    ds_mod.dataset_service = DatasetService()
    await ds_mod.dataset_service.load_dataset(str(ds_path))
    ep_mod.dataset_service = ds_mod.dataset_service
    ep_mod.episode_service = EpisodeService()
    yield ep_mod.episode_service
    settings.allowed_dataset_roots = original_roots


class TestEpisodeServiceReason:
    @pytest.mark.asyncio
    async def test_update_persists_reason(self, loaded_service):
        await loaded_service.update_episode(0, "bad", [], reason="motor jitter")
        ep = await loaded_service.get_episode(0)
        assert ep["grade"] == "bad"
        assert ep["reason"] == "motor jitter"

    @pytest.mark.asyncio
    async def test_switch_to_good_clears_reason(self, loaded_service):
        await loaded_service.update_episode(0, "bad", [], reason="too dark")
        await loaded_service.update_episode(0, "good", [], reason=None)
        ep = await loaded_service.get_episode(0)
        assert ep["grade"] == "good"
        assert ep["reason"] is None

    @pytest.mark.asyncio
    async def test_bulk_grade_applies_same_reason(self, loaded_service):
        await loaded_service.bulk_grade([0, 1, 2], "bad", reason="bad batch")
        for idx in (0, 1, 2):
            ep = await loaded_service.get_episode(idx)
            assert ep["grade"] == "bad"
            assert ep["reason"] == "bad batch"

    @pytest.mark.asyncio
    async def test_parquet_does_not_get_reason_column(self, loaded_service, tmp_path):
        await loaded_service.update_episode(0, "bad", [], reason="should-not-appear")
        # Read the parquet directly
        ds = next(tmp_path.glob("mock_ds"))
        pq_file = ds / "meta" / "episodes" / "chunk-000" / "file-000.parquet"
        table = pq.read_table(pq_file)
        assert "reason" not in table.schema.names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_grade_reason.py::TestEpisodeServiceReason -v`
Expected: FAIL — `update_episode` and `bulk_grade` don't accept `reason` kwarg.

- [ ] **Step 3: Edit `backend/datasets/services/episode_service.py`**

Replace `_load_annotations_from_db`:

```python
async def _load_annotations_from_db(dataset_id: int) -> dict[int, dict]:
    db = await get_db()
    async with db.execute(
        "SELECT episode_index, grade, tags, reason FROM episode_annotations WHERE dataset_id = ?",
        (dataset_id,),
    ) as cursor:
        rows = await cursor.fetchall()
    return {
        row[0]: {
            "grade": row[1],
            "tags": _json.loads(row[2]) if row[2] else [],
            "reason": row[3],
        }
        for row in rows
    }
```

Replace `_save_annotation_to_db`:

```python
async def _save_annotation_to_db(
    dataset_id: int,
    episode_index: int,
    grade: str | None,
    tags: list[str],
    reason: str | None,
) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO episode_annotations (dataset_id, episode_index, grade, tags, reason, updated_at)
           VALUES (?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
           ON CONFLICT(dataset_id, episode_index) DO UPDATE SET
             grade=excluded.grade, tags=excluded.tags, reason=excluded.reason,
             updated_at=excluded.updated_at""",
        (dataset_id, episode_index, grade, _json.dumps(tags), reason),
    )
    await db.commit()
```

Update the merge in `EpisodeService.get_episodes` so it pipes `reason` through (around line 287-291):

```python
                ann = annotations.get(ep["episode_index"])
                if ann:
                    ep["grade"] = ann.get("grade")
                    ep["tags"] = ann.get("tags", [])
                    ep["reason"] = ann.get("reason")
                episodes[ep["episode_index"]] = ep
```

Update the merge in `EpisodeService.get_episode` similarly (around line 321-324):

```python
                ann = annotations.get(episode_index)
                if ann:
                    ep["grade"] = ann.get("grade")
                    ep["tags"] = ann.get("tags", [])
                    ep["reason"] = ann.get("reason")
                return ep
```

Replace `EpisodeService.update_episode`:

```python
    async def update_episode(
        self,
        episode_index: int,
        grade: str | None,
        tags: list[str],
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Persist grade, tags, and reason to the SQLite DB."""
        if dataset_service.episodes_cache is not None:
            if episode_index not in dataset_service.episodes_cache:
                raise EpisodeNotFoundError(f"Episode {episode_index} not found.")
        else:
            file_path = dataset_service.get_file_for_episode(episode_index)
            if file_path is None:
                raise EpisodeNotFoundError(f"Episode {episode_index} not found.")

        # Reason is meaningless without bad/normal grade; null it out for good or unset.
        effective_reason = reason if grade in ("bad", "normal") else None

        dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
        await _ensure_migrated(dataset_id, dataset_service.dataset_path)
        await _save_annotation_to_db(dataset_id, episode_index, grade, tags, effective_reason)
        await _refresh_dataset_stats(dataset_id)

        # Parquet write does NOT include reason — by design.
        await _write_annotations_to_parquet({episode_index: (grade, tags)})

        dataset_service.distribution_cache.pop("grade:auto", None)
        dataset_service.distribution_cache.pop("grade:bar", None)
        dataset_service.distribution_cache.pop("tags:auto", None)
        dataset_service.distribution_cache.pop("tags:bar", None)

        if dataset_service.episodes_cache is not None:
            ep = dataset_service.episodes_cache.get(episode_index)
            if ep:
                ep["grade"] = grade
                ep["tags"] = tags
                ep["reason"] = effective_reason
                return ep

        return await self.get_episode(episode_index)
```

Replace `EpisodeService.bulk_grade`:

```python
    async def bulk_grade(
        self,
        episode_indices: list[int],
        grade: str,
        reason: str | None = None,
    ) -> int:
        """Set grade and reason for multiple episodes at once. Returns count updated."""
        dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
        await _ensure_migrated(dataset_id, dataset_service.dataset_path)

        effective_reason = reason if grade in ("bad", "normal") else None

        existing_annotations = await _load_annotations_from_db(dataset_id)
        parquet_updates: dict[int, tuple[str | None, list[str]]] = {}
        for idx in episode_indices:
            existing = existing_annotations.get(idx, {})
            tags = existing.get("tags", [])
            await _save_annotation_to_db(dataset_id, idx, grade, tags, effective_reason)
            parquet_updates[idx] = (grade, tags)
        await _refresh_dataset_stats(dataset_id)

        await _write_annotations_to_parquet(parquet_updates)

        dataset_service.distribution_cache.pop("grade:auto", None)
        dataset_service.distribution_cache.pop("grade:bar", None)
        dataset_service.distribution_cache.pop("tags:auto", None)
        dataset_service.distribution_cache.pop("tags:bar", None)

        if dataset_service.episodes_cache is not None:
            for idx in episode_indices:
                ep = dataset_service.episodes_cache.get(idx)
                if ep:
                    ep["grade"] = grade
                    ep["reason"] = effective_reason

        return len(episode_indices)
```

Update `_row_to_episode` (around line 439-462) so the `Episode` constructor doesn't drop `reason`. The function builds an `Episode` from a parquet row — parquet has no `reason`, so just don't pass it. The DB merge in `get_episode(s)` will set it. The existing `_row_to_episode` is correct as-is; do NOT add `reason=row.get("reason")`. Confirm by reading the file — no change needed in this function.

Also update `_ensure_migrated` so the legacy sidecar import passes `reason=None` (it never has one). Find the `INSERT OR IGNORE` near line 162-165 and replace with:

```python
        await db.execute(
            "INSERT OR IGNORE INTO episode_annotations (dataset_id, episode_index, grade, tags, reason) VALUES (?, ?, ?, ?, NULL)",
            (dataset_id, int(idx_str), ann.get("grade"), _json.dumps(ann.get("tags", []))),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_grade_reason.py::TestEpisodeServiceReason -v`
Expected: PASS (4 tests).

Also run the existing real-service tests to catch regressions:

Run: `pytest tests/test_episode_service_real.py tests/test_episode_annotations_db.py -v`
Expected: All previously passing tests still PASS. (`reason` defaulting to `None` keeps old call sites compatible.)

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/services/episode_service.py tests/test_grade_reason.py
git commit -m "feat(episode_service): persist reason in DB, never in parquet"
```

---

## Task 4: Forward `reason` through the router

**Files:**
- Modify: `backend/datasets/routers/episodes.py`
- Test: `tests/test_grade_reason.py`

- [ ] **Step 1: Write the failing router test**

Append to `tests/test_grade_reason.py`:

```python
class TestRouter:
    @pytest.mark.asyncio
    async def test_patch_with_reason_persists(self, loaded_service):
        from fastapi.testclient import TestClient

        from backend.main import app
        with TestClient(app) as client:
            r = client.patch(
                "/api/episodes/0",
                json={"grade": "bad", "tags": [], "reason": "lighting bad"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["grade"] == "bad"
            assert body["reason"] == "lighting bad"

    @pytest.mark.asyncio
    async def test_patch_bad_without_reason_rejected(self, loaded_service):
        from fastapi.testclient import TestClient

        from backend.main import app
        with TestClient(app) as client:
            r = client.patch("/api/episodes/0", json={"grade": "bad", "tags": []})
            assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_patch_good_clears_reason(self, loaded_service):
        from fastapi.testclient import TestClient

        from backend.main import app
        with TestClient(app) as client:
            r = client.patch("/api/episodes/0", json={"grade": "bad", "tags": [], "reason": "x"})
            assert r.status_code == 200
            r = client.patch("/api/episodes/0", json={"grade": "good", "tags": []})
            assert r.status_code == 200
            assert r.json()["reason"] is None

    @pytest.mark.asyncio
    async def test_bulk_grade_with_reason(self, loaded_service):
        from fastapi.testclient import TestClient

        from backend.main import app
        with TestClient(app) as client:
            r = client.post(
                "/api/episodes/bulk-grade",
                json={"episode_indices": [0, 1], "grade": "bad", "reason": "batch fail"},
            )
            assert r.status_code == 200
            assert r.json()["updated"] == 2
            # Confirm via GET
            r = client.get("/api/episodes/0")
            assert r.json()["reason"] == "batch fail"

    @pytest.mark.asyncio
    async def test_bulk_grade_bad_without_reason_rejected(self, loaded_service):
        from fastapi.testclient import TestClient

        from backend.main import app
        with TestClient(app) as client:
            r = client.post(
                "/api/episodes/bulk-grade",
                json={"episode_indices": [0, 1], "grade": "bad"},
            )
            assert r.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_grade_reason.py::TestRouter -v`
Expected: FAIL — router does not pass `reason` through.

- [ ] **Step 3: Edit `backend/datasets/routers/episodes.py`**

Replace the file with:

```python
from fastapi import APIRouter, HTTPException

from backend.datasets.schemas import BulkGradeRequest, Episode, EpisodeUpdate
from backend.datasets.services.episode_service import episode_service, EpisodeNotFoundError

router = APIRouter(prefix="/api/episodes", tags=["episodes"])


@router.get("", response_model=list[Episode])
async def list_episodes():
    try:
        return await episode_service.get_episodes()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{episode_index}", response_model=Episode)
async def get_episode(episode_index: int):
    try:
        return await episode_service.get_episode(episode_index)
    except EpisodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{episode_index}", response_model=Episode)
async def update_episode(episode_index: int, update: EpisodeUpdate):
    try:
        # When tags not provided, preserve existing tags instead of erasing
        if update.tags is not None:
            tags = update.tags
        else:
            current = await episode_service.get_episode(episode_index)
            tags = current.get("tags", [])
        return await episode_service.update_episode(
            episode_index=episode_index,
            grade=update.grade,
            tags=tags,
            reason=update.reason,
        )
    except EpisodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/bulk-grade")
async def bulk_grade_episodes(req: BulkGradeRequest):
    try:
        count = await episode_service.bulk_grade(
            req.episode_indices, req.grade, reason=req.reason,
        )
        return {"updated": count}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_grade_reason.py::TestRouter -v`
Expected: PASS (5 tests).

Run the full backend suite to catch regressions:

Run: `pytest tests/ -x`
Expected: All tests PASS. Stop on first failure (`-x`) to debug quickly.

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/routers/episodes.py tests/test_grade_reason.py
git commit -m "feat(api): forward reason through PATCH /episodes and POST /bulk-grade"
```

---

## Task 5: Frontend types + `useEpisodes` hook

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/hooks/useEpisodes.ts`

- [ ] **Step 1: Edit `frontend/src/types/index.ts`**

In the `Episode` interface (line 16), add `reason: string | null` between `tags` and `created_at`:

```ts
export interface Episode {
  episode_index: number
  length: number
  task_index: number
  task_instruction: string
  chunk_index: number
  file_index: number
  dataset_from_index: number
  dataset_to_index: number
  grade: string | null
  tags: string[]
  reason: string | null
  created_at: string | null
}
```

In the `EpisodeUpdate` interface (line 35), add `reason`:

```ts
export interface EpisodeUpdate {
  grade: string | null
  tags: string[]
  reason?: string | null
}
```

- [ ] **Step 2: Edit `frontend/src/hooks/useEpisodes.ts`**

Replace the `UseEpisodesReturn` and `updateEpisode` so they accept reason:

```ts
import { useState, useCallback } from 'react'
import client from '../api/client'
import type { Episode, EpisodeUpdate } from '../types'

interface UseEpisodesReturn {
  episodes: Episode[]
  selectedEpisode: Episode | null
  loading: boolean
  error: string | null
  fetchEpisodes: () => Promise<void>
  selectEpisode: (index: number) => void
  updateEpisode: (
    index: number,
    grade: string | null,
    tags: string[],
    reason?: string | null,
  ) => Promise<void>
}

export function useEpisodes(): UseEpisodesReturn {
  const [episodes, setEpisodes] = useState<Episode[]>([])
  const [selectedEpisode, setSelectedEpisode] = useState<Episode | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchEpisodes = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await client.get<Episode[]>('/episodes')
      setEpisodes(response.data)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch episodes'
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [])

  const selectEpisode = useCallback((index: number) => {
    setEpisodes(prev => {
      const ep = prev.find(e => e.episode_index === index) ?? null
      setSelectedEpisode(ep)
      return prev
    })
  }, [])

  const updateEpisode = useCallback(
    async (index: number, grade: string | null, tags: string[], reason: string | null = null) => {
      const update: EpisodeUpdate = { grade, tags, reason }
      const response = await client.patch<Episode>(`/episodes/${index}`, update)
      const updated = response.data
      setEpisodes(prev => prev.map(e => e.episode_index === index ? updated : e))
      setSelectedEpisode(prev => prev?.episode_index === index ? updated : prev)
    },
    [],
  )

  return { episodes, selectedEpisode, loading, error, fetchEpisodes, selectEpisode, updateEpisode }
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run build`
Expected: Build succeeds. Other call sites of `updateEpisode` continue to compile because `reason` is optional.

If the build fails because some other component passes `Episode` without `reason`, that means the backend didn't populate it for that case — fix by making `reason` optional in those mock objects, **not** by removing it from the interface.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/hooks/useEpisodes.ts
git commit -m "feat(frontend): extend Episode types and useEpisodes with reason"
```

---

## Task 6: Create `GradeReasonModal`

**Files:**
- Create: `frontend/src/components/GradeReasonModal.tsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Create the modal component**

Create `frontend/src/components/GradeReasonModal.tsx` with the full content:

```tsx
import { useEffect, useRef, useState } from 'react'

interface GradeReasonModalProps {
  open: boolean
  grade: 'normal' | 'bad'
  initialReason?: string
  episodeCount?: number
  onSave: (reason: string) => void
  onCancel: () => void
}

const GRADE_COLORS: Record<'normal' | 'bad', string> = {
  normal: 'var(--c-yellow)',
  bad: 'var(--c-red)',
}

const GRADE_TITLES: Record<'normal' | 'bad', string> = {
  normal: 'Mark as Normal',
  bad: 'Mark as Bad',
}

export function GradeReasonModal({
  open,
  grade,
  initialReason = '',
  episodeCount,
  onSave,
  onCancel,
}: GradeReasonModalProps) {
  const [reason, setReason] = useState(initialReason)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Reset reason whenever the modal (re)opens with a new initial value.
  useEffect(() => {
    if (open) {
      setReason(initialReason)
      // Defer focus until the textarea is mounted.
      requestAnimationFrame(() => textareaRef.current?.focus())
    }
  }, [open, initialReason])

  if (!open) return null

  const trimmed = reason.trim()
  const canSave = trimmed.length > 0
  const color = GRADE_COLORS[grade]
  const title = GRADE_TITLES[grade]
  const isBulk = (episodeCount ?? 1) > 1

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      onCancel()
      return
    }
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      if (canSave) onSave(trimmed)
    }
    // Plain Enter falls through → newline (default textarea behavior).
  }

  return (
    <div
      className="grade-reason-overlay"
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="grade-reason-panel"
        onClick={(e) => e.stopPropagation()}
        style={{ borderTopColor: color }}
      >
        <div className="grade-reason-header" style={{ color }}>
          {title}
        </div>
        {isBulk && (
          <div className="grade-reason-subheader">
            Apply to {episodeCount} episodes
          </div>
        )}
        <textarea
          ref={textareaRef}
          className="grade-reason-textarea"
          rows={5}
          value={reason}
          placeholder="Why is this episode being graded this way?"
          onChange={(e) => setReason(e.target.value)}
          onKeyDown={handleKeyDown}
        />
        <div className="grade-reason-footer">
          <span className="grade-reason-hint">
            <kbd>Esc</kbd> cancel · <kbd>⌘/Ctrl+Enter</kbd> save
          </span>
          <div className="grade-reason-actions">
            <button className="grade-reason-btn" onClick={onCancel}>
              Cancel
            </button>
            <button
              className="grade-reason-btn primary"
              disabled={!canSave}
              onClick={() => canSave && onSave(trimmed)}
              style={{ background: canSave ? color : undefined }}
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Add modal styles to `frontend/src/App.css`**

Append to the end of `frontend/src/App.css`:

```css
/* Grade reason modal */
.grade-reason-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.grade-reason-panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-top: 3px solid var(--text-dim);
  border-radius: 8px;
  padding: 16px 18px 14px;
  width: min(440px, 90vw);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.grade-reason-header {
  font-size: 14px;
  font-weight: 600;
}

.grade-reason-subheader {
  font-size: 11px;
  color: var(--text-dim);
}

.grade-reason-textarea {
  width: 100%;
  background: var(--panel2);
  color: var(--text);
  border: 1px solid var(--border2);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
  resize: vertical;
  min-height: 90px;
}

.grade-reason-textarea:focus {
  outline: none;
  border-color: var(--accent);
}

.grade-reason-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.grade-reason-hint {
  font-size: 10px;
  color: var(--text-dim);
}

.grade-reason-hint kbd {
  background: var(--panel2);
  border: 1px solid var(--border2);
  border-radius: 3px;
  padding: 1px 5px;
  font-size: 10px;
  margin: 0 2px;
}

.grade-reason-actions {
  display: flex;
  gap: 8px;
}

.grade-reason-btn {
  background: var(--panel2);
  color: var(--text);
  border: 1px solid var(--border2);
  border-radius: 5px;
  padding: 6px 14px;
  font-size: 12px;
  cursor: pointer;
}

.grade-reason-btn:hover:not(:disabled) {
  background: var(--border2);
}

.grade-reason-btn.primary {
  color: #000;
  border: none;
  font-weight: 600;
}

.grade-reason-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.grade-reason-display {
  font-size: 11px;
  color: var(--text-dim);
  padding: 6px 12px 0;
  font-style: italic;
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/GradeReasonModal.tsx frontend/src/App.css
git commit -m "feat(frontend): add GradeReasonModal component with keyboard shortcuts"
```

---

## Task 7: Wire `GradeReasonModal` into `DatasetPage`

**Files:**
- Modify: `frontend/src/components/DatasetPage.tsx`

- [ ] **Step 1: Import the modal and add state**

At the top of `frontend/src/components/DatasetPage.tsx`, add the import alongside the other component imports:

```tsx
import { GradeReasonModal } from './GradeReasonModal'
```

Inside `DatasetPage` (after the existing `useState` declarations), add:

```tsx
const [reasonModal, setReasonModal] = useState<{
  grade: 'normal' | 'bad'
  initialReason: string
  pendingTags: string[]
} | null>(null)
```

- [ ] **Step 2: Extend `handleSaveEpisode` to forward the reason**

Replace the existing `handleSaveEpisode` (around line 88-108) with:

```tsx
const handleSaveEpisode = useCallback(
  async (
    index: number,
    grade: string | null,
    tags: string[],
    reason: string | null = null,
  ) => {
    await updateEpisode(index, grade, tags, reason)
    if (grade) {
      const currentIdx = curateEpisodes.findIndex(e => e.episode_index === index)
      const ungradedInView = curateEpisodes.filter(e => !e.grade)
      const nextUngraded = ungradedInView.find(e => {
        const i = curateEpisodes.indexOf(e)
        return i > currentIdx
      }) ?? ungradedInView.find(e => {
        const i = curateEpisodes.indexOf(e)
        return i < currentIdx
      })
      if (nextUngraded) {
        setSelectedEpisode(nextUngraded)
        return
      }
    }
    setSelectedEpisode(prev =>
      prev?.episode_index === index ? { ...prev, grade, tags, reason } : prev,
    )
  },
  [updateEpisode, curateEpisodes],
)
```

- [ ] **Step 3: Add a `requestGrade` wrapper that opens the modal for bad/normal**

Add **after** `handleSaveEpisode` and **before** `navigateEpisode`:

```tsx
const requestGrade = useCallback(
  (grade: 'good' | 'normal' | 'bad') => {
    if (!selectedEpisode) return
    if (grade === 'good') {
      // good clears any prior reason (server enforces this too)
      void handleSaveEpisode(selectedEpisode.episode_index, grade, selectedEpisode.tags, null)
      return
    }
    setReasonModal({
      grade,
      initialReason: selectedEpisode.reason ?? '',
      pendingTags: selectedEpisode.tags,
    })
  },
  [selectedEpisode, handleSaveEpisode],
)
```

- [ ] **Step 4: Route the keyboard shortcut and grade-bar buttons through `requestGrade`**

Replace `quickGrade` with:

```tsx
const quickGrade = useCallback(
  (key: string) => {
    const grade = GRADE_KEYS[key] as 'good' | 'normal' | 'bad' | undefined
    if (grade) requestGrade(grade)
  },
  [requestGrade],
)
```

The `case '1' / '2' / '3'` block in the keyboard handler already invokes `quickGrade(e.key)`. Update the same handler to skip grade shortcuts when the modal is open. Inside the existing keydown handler add a guard at the top (right after the INPUT/TEXTAREA early return):

```tsx
if (reasonModal) return  // Modal is open: let the textarea consume keys.
```

Update the dependency array of the `useEffect`:

```tsx
}, [navigateEpisode, quickGrade, reasonModal])
```

In the grade-bar JSX (around line 222-241), replace the button `onClick`:

```tsx
onClick={() => requestGrade(g)}
```

(Keep the rest of the grade-button rendering unchanged.)

- [ ] **Step 5: Render the modal and the existing-reason display**

Just below the closing `</div>` of `grade-bar` (still inside the `selectedEpisode &&` block), insert the reason display:

```tsx
{selectedEpisode.reason && (
  <div className="grade-reason-display">
    Reason: {selectedEpisode.reason}
  </div>
)}
```

Render the modal at the end of the component, just before the final `</div>` that closes `dataset-page`:

```tsx
<GradeReasonModal
  open={reasonModal !== null}
  grade={reasonModal?.grade ?? 'bad'}
  initialReason={reasonModal?.initialReason}
  onSave={(reason) => {
    if (!selectedEpisode || !reasonModal) return
    const m = reasonModal
    setReasonModal(null)
    void handleSaveEpisode(
      selectedEpisode.episode_index,
      m.grade,
      m.pendingTags,
      reason,
    )
  }}
  onCancel={() => setReasonModal(null)}
/>
```

- [ ] **Step 6: Typecheck and run dev server**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

Run: `cd frontend && npm run dev` (in background)

Open the curate tab in the browser, pick an episode, then verify manually:
- Click `bad` button → modal opens, focused on textarea.
- Type a reason, press `Cmd/Ctrl+Enter` → modal closes, episode is graded `bad`, list auto-jumps to next ungraded, reason text shows under grade-bar.
- Press `2` (normal shortcut) on a fresh episode → modal opens for `normal`.
- Press Esc inside modal → modal closes, no grade change.
- Click `bad` on an already-bad episode → modal opens with prior reason prefilled.
- Click `good` → no modal, grade becomes `good`, reason display disappears.
- With modal open, press `1` / `2` / `3` → key is consumed by textarea (typed as character), no grade change behind the scenes.
- With modal open, press `↑`/`↓` → episode list does NOT navigate.

If any step fails, fix it before continuing.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/DatasetPage.tsx
git commit -m "feat(frontend): require reason for bad/normal in DatasetPage"
```

---

## Task 8: Wire `GradeReasonModal` into `OverviewTab` bulk grade

**Files:**
- Modify: `frontend/src/components/OverviewTab.tsx`

- [ ] **Step 1: Import the modal and add state**

Add the import at the top of `frontend/src/components/OverviewTab.tsx`:

```tsx
import { GradeReasonModal } from './GradeReasonModal'
```

Inside `OverviewTab`, add state below the existing `useState` calls:

```tsx
const [bulkReasonModal, setBulkReasonModal] = useState<{
  episodeIndices: number[]
  field: string
  label: string
} | null>(null)
```

- [ ] **Step 2: Replace `handleBulkBad` so it stages the modal instead of posting immediately**

Replace `handleBulkBad` with two functions: `openBulkBadModal` (compute indices and open the modal) and `submitBulkBad` (called from the modal `onSave`):

```tsx
const openBulkBadModal = useCallback((menu: ContextMenuState) => {
  const indices: number[] = []
  if (menu.field === 'length') {
    const parts = menu.label.split('-').map(Number)
    if (parts.length === 2 && parts.every(n => !isNaN(n))) {
      for (const ep of episodes) {
        if (ep.length >= parts[0] && ep.length < parts[1]) indices.push(ep.episode_index)
      }
    }
  } else if (menu.field === 'tags') {
    for (const ep of episodes) {
      if (ep.tags.includes(menu.label)) indices.push(ep.episode_index)
    }
  }
  if (indices.length === 0) return
  setBulkReasonModal({ episodeIndices: indices, field: menu.field, label: menu.label })
  setContextMenu(null)
}, [episodes])

const submitBulkBad = useCallback(
  async (reason: string) => {
    const m = bulkReasonModal
    if (!m) return
    setBulkReasonModal(null)
    await client.post('/episodes/bulk-grade', {
      episode_indices: m.episodeIndices,
      grade: 'bad',
      reason,
    })
    void addChart(datasetPath, m.field, m.field === 'length' ? 'histogram' : 'auto')
    void addChart(datasetPath, 'grade', 'auto')
  },
  [bulkReasonModal, datasetPath, addChart],
)
```

- [ ] **Step 3: Update the context-menu button to call `openBulkBadModal`**

Find the button at the existing `handleBulkBad(contextMenu)` call site (around line 215) and change `onClick`:

```tsx
onClick={() => openBulkBadModal(contextMenu)}
```

Remove the now-unused `handleBulkBad` function entirely.

- [ ] **Step 4: Render the modal**

At the end of the component, just before the final `</div>` that closes `overview-layout`, render:

```tsx
<GradeReasonModal
  open={bulkReasonModal !== null}
  grade="bad"
  initialReason=""
  episodeCount={bulkReasonModal?.episodeIndices.length}
  onSave={(reason) => void submitBulkBad(reason)}
  onCancel={() => setBulkReasonModal(null)}
/>
```

- [ ] **Step 5: Typecheck and manual verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

Reload the dev server, open the **Overview** tab, right-click any bar in the Length or Tags chart → "Mark as Bad" → confirm modal opens with `Apply to N episodes`. Type a reason, save. Switch to the **Curate** tab and confirm those episodes now show `bad` grade and the reason in the side panel.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/OverviewTab.tsx
git commit -m "feat(frontend): require reason for bulk Mark as Bad"
```

---

## Final Verification

- [ ] **Run the full backend test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS, including the new `test_grade_reason.py`.

- [ ] **Run the frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no TypeScript errors.

- [ ] **End-to-end smoke test in the browser**

Start backend (e.g. `./start.sh` or whatever the project uses) and frontend (`cd frontend && npm run dev`). Walk through:

1. Load a dataset.
2. On Curate tab: grade one episode as `bad` with reason "test bad" → verify the reason shows under the grade-bar after the auto-jump returns to that episode (use ↑/↓ to navigate back).
3. Re-click `bad` on the same episode → modal opens with "test bad" prefilled. Edit and save.
4. Click `good` on the same episode → reason display vanishes.
5. On Overview tab: right-click a bar in the Tags chart → Mark as Bad → enter reason → save. Confirm those episodes have `bad` grade.
6. Quit the app, restart, reload the dataset, confirm reasons persisted.

- [ ] **Confirm parquet stays clean**

```bash
python - <<'EOF'
import pyarrow.parquet as pq
from pathlib import Path
import os
ds = os.environ.get("CT_DATASET")  # set this to the dataset path you tested with
for f in Path(ds).rglob("meta/episodes/**/*.parquet"):
    t = pq.read_table(f)
    assert "reason" not in t.schema.names, f"LEAK in {f}"
    print("OK", f)
EOF
```

Expected: every file prints `OK`. If any prints `LEAK`, you accidentally wrote `reason` into parquet — fix `_write_annotations_to_parquet` and re-run.

---

## Self-Review (filled in by the planner)

**Spec coverage:** Every spec section has a task — DB migration (Task 1), schemas (Task 2), service (Task 3), router (Task 4), frontend types/hook (Task 5), modal component (Task 6), DatasetPage integration with single-episode flow + reason display + keyboard guard (Task 7), OverviewTab bulk integration (Task 8), edge cases & verification covered in Task 7 manual steps and Final Verification. The spec's mention of "PUT" was reconciled with the actual `PATCH` endpoint, and the keyboard shortcuts are the real `1`/`2`/`3` keys (the spec's `g`/`n`/`b` were illustrative).

**Placeholder scan:** No TBDs, no "implement later", every code step shows the actual code.

**Type consistency:** `update_episode(idx, grade, tags, reason)` signature is consistent across service (Task 3), router (Task 4), hook (Task 5), and DatasetPage (Task 7). `EpisodeUpdate` shape matches in schemas (Task 2) and frontend types (Task 5). `GradeReasonModal` props match callers in both Task 7 and Task 8.
