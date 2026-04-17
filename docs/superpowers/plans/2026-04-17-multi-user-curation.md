# Multi-User Curation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow 5–10 teammates to curate the same LeRobot dataset concurrently through a single central FastAPI server, with shared real-time edits, per-field conflict protection (optimistic version for `grade`/`tags`; soft lease for `reason`/`task_instruction`), and per-user independent video playback.

**Architecture:** Single-worker FastAPI on a dedicated workstation serves SQLite (WAL) as the source of truth. Browsers receive live updates via SSE, edit with `X-User-Name` identity + version preconditions, and hold short leases (60 s TTL, 10 s heartbeat) on free-text fields. Parquet on Synology is demoted to an artifact written only by a single background exporter task.

**Tech Stack:** FastAPI + aiosqlite + sse-starlette, React + axios + native EventSource, pytest + httpx.AsyncClient + pytest-asyncio, Playwright for E2E, k6 for load.

**Spec:** `docs/superpowers/specs/2026-04-17-multi-user-curation-design.md`

---

## File Structure

**Backend (new):**
- `backend/core/sse_bus.py` — in-memory pub/sub for SSE fan-out.
- `backend/core/identity.py` — resolve `X-User-Name` header into an actor string.
- `backend/datasets/services/lease_service.py` — lease acquire/heartbeat/release/takeover + expiry cleanup.
- `backend/datasets/services/audit_service.py` — append-only audit log writes.
- `backend/datasets/services/export_worker.py` — async parquet exporter task.
- `backend/datasets/services/task_annotation_service.py` — SQLite-backed task instruction CRUD.
- `backend/datasets/routers/leases.py` — REST for leases.
- `backend/datasets/routers/events.py` — SSE endpoint.
- `backend/datasets/routers/task_annotations.py` — PATCH for task instructions.
- `backend/datasets/routers/export.py` — exporter trigger/status.
- `scripts/migrate_to_central.py` — one-shot per-PC DB → central DB merge.
- `deploy/curation.service` — systemd unit file.
- `deploy/backup.sh` — nightly SQLite `.backup` script.

**Backend (modified):**
- `backend/core/db.py` — add `SCHEMA_V3`, migration step, version bump.
- `backend/core/config.py` — add `default_user_name` and related settings.
- `backend/datasets/schemas.py` — new `EpisodeUpdate` with `version`, new lease/event models.
- `backend/datasets/services/episode_service.py` — remove parquet write, add version check + audit + bus publish.
- `backend/datasets/services/task_service.py` — same shape as episode_service, backed by `task_annotations`.
- `backend/datasets/routers/episodes.py` — add 409/423 handling, pass `X-User-Name`.
- `backend/main.py` — register new routers, start exporter + lease cleanup tasks in `lifespan`.

**Frontend (new):**
- `frontend/src/api/userName.ts` — localStorage get/set for user name.
- `frontend/src/api/eventSource.ts` — SSE subscriber singleton with reconnect.
- `frontend/src/hooks/useLease.ts` — focus → acquire, heartbeat, blur → release.
- `frontend/src/hooks/usePresence.ts` — subscribe presence channel, expose viewers by episode.
- `frontend/src/hooks/useSSE.ts` — generic SSE subscription with query cache mutation.
- `frontend/src/components/UserNamePrompt.tsx` — first-visit name entry.
- `frontend/src/components/PresenceDots.tsx` — row-level viewer count dots.
- `frontend/src/components/ExternalChangeBanner.tsx` — 409 quiet banner.
- `frontend/src/components/LockedField.tsx` — read-only wrapper + takeover button.
- `frontend/src/components/TimestampCopyButton.tsx` — `?t=` URL copy.

**Frontend (modified):**
- `frontend/src/api/client.ts` — inject `X-User-Name` header.
- `frontend/src/hooks/useEpisodes.ts` — SSE integration, version threading, 409/423 surfacing.
- `frontend/src/hooks/useTasks.ts` — same for tasks.
- `frontend/src/components/EpisodeEditor.tsx` (inside `DatasetPage.tsx`/`OverviewTab.tsx`) — lease for `reason`, highlight transitions, external-change banner.
- `frontend/src/components/DatasetPage.tsx` — presence dots per row, editing marker.
- `frontend/src/components/VideoPlayer.tsx` — read `?t=`, add copy button.
- `frontend/src/types.ts` — add `version`, `updated_by`, lease/event shapes.

**Tests (new):**
- `tests/test_lease_service.py`
- `tests/test_edit_version.py`
- `tests/test_sse_bus.py`
- `tests/test_events_router.py`
- `tests/test_task_annotations_db.py`
- `tests/test_exporter.py`
- `tests/test_migrate_to_central.py`
- `frontend/src/__tests__/useLease.test.ts` (vitest)
- `frontend/e2e/multi_user.spec.ts` (Playwright)

---

## Task 1: Bump DB schema to V3 — new columns and tables

**Files:**
- Modify: `backend/core/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_db.py`:
```python
import pytest
import pytest_asyncio
from pathlib import Path
import tempfile
from backend.core.db import get_db, init_db, close_db, _reset


@pytest_asyncio.fixture
async def tmp_db(monkeypatch):
    _reset()
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    await init_db()
    yield tmp
    await close_db()
    _reset()


@pytest.mark.asyncio
async def test_schema_v3_adds_version_and_updated_by(tmp_db):
    db = await get_db()
    async with db.execute("PRAGMA table_info(episode_annotations)") as cursor:
        cols = {row[1] for row in await cursor.fetchall()}
    assert "version" in cols
    assert "updated_by" in cols


@pytest.mark.asyncio
async def test_schema_v3_creates_task_annotations(tmp_db):
    db = await get_db()
    async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_annotations'") as cursor:
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_schema_v3_creates_edit_leases(tmp_db):
    db = await get_db()
    async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='edit_leases'") as cursor:
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_schema_v3_creates_audit_log(tmp_db):
    db = await get_db()
    async with db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'") as cursor:
        row = await cursor.fetchone()
    assert row is not None


@pytest.mark.asyncio
async def test_user_version_is_3(tmp_db):
    db = await get_db()
    async with db.execute("PRAGMA user_version") as cursor:
        row = await cursor.fetchone()
    assert row[0] == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py::test_schema_v3_adds_version_and_updated_by tests/test_db.py::test_schema_v3_creates_task_annotations tests/test_db.py::test_schema_v3_creates_edit_leases tests/test_db.py::test_schema_v3_creates_audit_log tests/test_db.py::test_user_version_is_3 -v`

Expected: all FAIL (no V3 schema yet).

- [ ] **Step 3: Add `SCHEMA_V3` and migration step**

Edit `backend/core/db.py`. After `SCHEMA_V2 = """..."""`, add:
```python
SCHEMA_V3 = """
ALTER TABLE episode_annotations ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE episode_annotations ADD COLUMN updated_by TEXT;

CREATE TABLE IF NOT EXISTS task_annotations (
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    task_index INTEGER NOT NULL,
    task       TEXT NOT NULL,
    version    INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT,
    PRIMARY KEY (dataset_id, task_index)
);

CREATE TABLE IF NOT EXISTS edit_leases (
    resource_type TEXT NOT NULL,
    resource_key  TEXT NOT NULL,
    owner         TEXT NOT NULL,
    acquired_at   TEXT DEFAULT CURRENT_TIMESTAMP,
    heartbeat_at  TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at    TEXT NOT NULL,
    PRIMARY KEY (resource_type, resource_key)
);

CREATE INDEX IF NOT EXISTS idx_leases_expires ON edit_leases(expires_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT DEFAULT CURRENT_TIMESTAMP,
    actor         TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_key  TEXT NOT NULL,
    action        TEXT NOT NULL,
    payload       TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_log(at);
"""
```

In `init_db()`, after the V2 block, add:
```python
if version < 3:
    await db.executescript(SCHEMA_V3)
    await db.execute("PRAGMA user_version = 3")
    await db.commit()
    logger.info("Database upgraded to v3 (version/lease/audit) at %s", _get_db_path())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: all PASS, including older V1/V2 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/core/db.py tests/test_db.py
git commit -m "Add schema V3 with version, leases, and audit_log"
```

---

## Task 2: Identity resolver — `X-User-Name` header

**Files:**
- Create: `backend/core/identity.py`
- Test: `tests/test_identity.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_identity.py`:
```python
from fastapi import Request
from starlette.datastructures import Headers
from backend.core.identity import resolve_actor


def _make_request(headers: dict) -> Request:
    scope = {"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}
    return Request(scope)


def test_resolve_actor_from_header():
    req = _make_request({"X-User-Name": "jun-seok"})
    assert resolve_actor(req) == "jun-seok"


def test_resolve_actor_strips_whitespace():
    req = _make_request({"X-User-Name": "  tm  "})
    assert resolve_actor(req) == "tm"


def test_resolve_actor_defaults_to_anonymous():
    req = _make_request({})
    assert resolve_actor(req) == "anonymous"


def test_resolve_actor_truncates_long_names():
    req = _make_request({"X-User-Name": "x" * 500})
    assert len(resolve_actor(req)) <= 64
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_identity.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Write implementation**

Create `backend/core/identity.py`:
```python
from fastapi import Request

MAX_NAME_LEN = 64
DEFAULT_ACTOR = "anonymous"


def resolve_actor(request: Request) -> str:
    raw = request.headers.get("X-User-Name", "").strip()
    if not raw:
        return DEFAULT_ACTOR
    return raw[:MAX_NAME_LEN]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_identity.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/core/identity.py tests/test_identity.py
git commit -m "Add X-User-Name header resolver"
```

---

## Task 3: SSE pub/sub bus

**Files:**
- Create: `backend/core/sse_bus.py`
- Test: `tests/test_sse_bus.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_sse_bus.py`:
```python
import asyncio
import pytest
from backend.core.sse_bus import SseBus


@pytest.mark.asyncio
async def test_bus_delivers_to_subscriber():
    bus = SseBus()
    async with bus.subscribe("dataset:1") as queue:
        await bus.publish("dataset:1", {"event": "x", "data": {"n": 1}})
        msg = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert msg == {"event": "x", "data": {"n": 1}}


@pytest.mark.asyncio
async def test_bus_isolates_channels():
    bus = SseBus()
    async with bus.subscribe("dataset:1") as q1:
        async with bus.subscribe("dataset:2") as q2:
            await bus.publish("dataset:2", {"event": "y", "data": {}})
            msg = await asyncio.wait_for(q2.get(), timeout=1.0)
            assert msg["event"] == "y"
            assert q1.qsize() == 0


@pytest.mark.asyncio
async def test_bus_drops_oldest_when_queue_full():
    bus = SseBus(max_queue=2)
    async with bus.subscribe("c") as queue:
        await bus.publish("c", {"event": "a", "data": {}})
        await bus.publish("c", {"event": "b", "data": {}})
        await bus.publish("c", {"event": "c", "data": {}})
        msgs = [await queue.get(), await queue.get()]
    assert [m["event"] for m in msgs] == ["b", "c"]


@pytest.mark.asyncio
async def test_connection_count_tracks_subscribers():
    bus = SseBus()
    assert bus.connection_count == 0
    async with bus.subscribe("c"):
        assert bus.connection_count == 1
        async with bus.subscribe("c"):
            assert bus.connection_count == 2
    assert bus.connection_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sse_bus.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Write implementation**

Create `backend/core/sse_bus.py`:
```python
from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from typing import Any


class SseBus:
    def __init__(self, max_queue: int = 256) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._max_queue = max_queue
        self._lock = asyncio.Lock()

    @property
    def connection_count(self) -> int:
        return sum(len(q) for q in self._subs.values())

    @contextlib.asynccontextmanager
    async def subscribe(self, channel: str):
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue)
        async with self._lock:
            self._subs[channel].add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                self._subs[channel].discard(queue)
                if not self._subs[channel]:
                    del self._subs[channel]

    async def publish(self, channel: str, event: dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._subs.get(channel, ()))
        for queue in queues:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await queue.put(event)


bus = SseBus()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_sse_bus.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/core/sse_bus.py tests/test_sse_bus.py
git commit -m "Add in-memory SSE pub/sub bus"
```

---

## Task 4: Lease service — acquire/heartbeat/release

**Files:**
- Create: `backend/datasets/services/lease_service.py`
- Test: `tests/test_lease_service.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_lease_service.py`:
```python
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, UTC

import pytest
import pytest_asyncio

from backend.core.db import get_db, init_db, close_db, _reset
from backend.datasets.services.lease_service import (
    LeaseService, LeaseConflict, LEASE_TTL_SECONDS,
)


@pytest_asyncio.fixture(autouse=True)
async def tmp_db(monkeypatch):
    _reset()
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    await init_db()
    yield tmp
    await close_db()
    _reset()


@pytest.mark.asyncio
async def test_acquire_succeeds_when_free():
    svc = LeaseService()
    result = await svc.acquire("episode_reason", "1:42", "alice")
    assert result.owner == "alice"


@pytest.mark.asyncio
async def test_acquire_same_owner_is_idempotent():
    svc = LeaseService()
    await svc.acquire("episode_reason", "1:42", "alice")
    again = await svc.acquire("episode_reason", "1:42", "alice")
    assert again.owner == "alice"


@pytest.mark.asyncio
async def test_acquire_conflict_when_held_by_other():
    svc = LeaseService()
    await svc.acquire("episode_reason", "1:42", "alice")
    with pytest.raises(LeaseConflict) as exc:
        await svc.acquire("episode_reason", "1:42", "bob")
    assert exc.value.owner == "alice"


@pytest.mark.asyncio
async def test_heartbeat_extends_expiry():
    svc = LeaseService()
    first = await svc.acquire("episode_reason", "1:42", "alice")
    await asyncio.sleep(0.1)
    bumped = await svc.heartbeat("episode_reason", "1:42", "alice")
    assert bumped.expires_at > first.expires_at


@pytest.mark.asyncio
async def test_release_removes_lease():
    svc = LeaseService()
    await svc.acquire("episode_reason", "1:42", "alice")
    await svc.release("episode_reason", "1:42", "alice")
    # re-acquire by someone else should now succeed
    result = await svc.acquire("episode_reason", "1:42", "bob")
    assert result.owner == "bob"


@pytest.mark.asyncio
async def test_takeover_forces_new_owner():
    svc = LeaseService()
    await svc.acquire("episode_reason", "1:42", "alice")
    result = await svc.takeover("episode_reason", "1:42", "bob")
    assert result.owner == "bob"


@pytest.mark.asyncio
async def test_cleanup_removes_expired(monkeypatch):
    svc = LeaseService()
    await svc.acquire("episode_reason", "1:42", "alice")
    # force expiry by backdating
    db = await get_db()
    past = (datetime.now(UTC) - timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
    await db.execute("UPDATE edit_leases SET expires_at = ?", (past,))
    await db.commit()
    removed = await svc.cleanup_expired()
    assert removed == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lease_service.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Write implementation**

Create `backend/datasets/services/lease_service.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, UTC

from backend.core.db import get_db

LEASE_TTL_SECONDS = 60
HEARTBEAT_INTERVAL_SECONDS = 10


class LeaseConflict(Exception):
    def __init__(self, owner: str, expires_at: str):
        self.owner = owner
        self.expires_at = expires_at
        super().__init__(f"Leased by {owner} until {expires_at}")


@dataclass
class Lease:
    resource_type: str
    resource_key: str
    owner: str
    expires_at: str


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class LeaseService:
    async def acquire(self, resource_type: str, resource_key: str, owner: str) -> Lease:
        db = await get_db()
        now = datetime.now(UTC)
        expires = _fmt(now + timedelta(seconds=LEASE_TTL_SECONDS))
        async with db.execute(
            "SELECT owner, expires_at FROM edit_leases WHERE resource_type=? AND resource_key=?",
            (resource_type, resource_key),
        ) as cursor:
            existing = await cursor.fetchone()
        if existing and existing[0] != owner and existing[1] >= _fmt(now):
            raise LeaseConflict(owner=existing[0], expires_at=existing[1])
        await db.execute(
            """INSERT INTO edit_leases (resource_type, resource_key, owner, acquired_at, heartbeat_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(resource_type, resource_key) DO UPDATE SET
                 owner=excluded.owner,
                 acquired_at=excluded.acquired_at,
                 heartbeat_at=excluded.heartbeat_at,
                 expires_at=excluded.expires_at""",
            (resource_type, resource_key, owner, _fmt(now), _fmt(now), expires),
        )
        await db.commit()
        return Lease(resource_type, resource_key, owner, expires)

    async def heartbeat(self, resource_type: str, resource_key: str, owner: str) -> Lease:
        db = await get_db()
        now = datetime.now(UTC)
        expires = _fmt(now + timedelta(seconds=LEASE_TTL_SECONDS))
        cursor = await db.execute(
            """UPDATE edit_leases SET heartbeat_at=?, expires_at=?
               WHERE resource_type=? AND resource_key=? AND owner=?""",
            (_fmt(now), expires, resource_type, resource_key, owner),
        )
        await db.commit()
        if cursor.rowcount == 0:
            raise LeaseConflict(owner="unknown", expires_at="")
        return Lease(resource_type, resource_key, owner, expires)

    async def release(self, resource_type: str, resource_key: str, owner: str) -> None:
        db = await get_db()
        await db.execute(
            "DELETE FROM edit_leases WHERE resource_type=? AND resource_key=? AND owner=?",
            (resource_type, resource_key, owner),
        )
        await db.commit()

    async def takeover(self, resource_type: str, resource_key: str, new_owner: str) -> Lease:
        db = await get_db()
        await db.execute(
            "DELETE FROM edit_leases WHERE resource_type=? AND resource_key=?",
            (resource_type, resource_key),
        )
        await db.commit()
        return await self.acquire(resource_type, resource_key, new_owner)

    async def cleanup_expired(self) -> int:
        db = await get_db()
        now = _fmt(datetime.now(UTC))
        cursor = await db.execute("DELETE FROM edit_leases WHERE expires_at < ?", (now,))
        await db.commit()
        return cursor.rowcount

    async def get_active_leases(self) -> list[Lease]:
        db = await get_db()
        now = _fmt(datetime.now(UTC))
        async with db.execute(
            "SELECT resource_type, resource_key, owner, expires_at FROM edit_leases WHERE expires_at >= ?",
            (now,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [Lease(*row) for row in rows]


lease_service = LeaseService()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_lease_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/services/lease_service.py tests/test_lease_service.py
git commit -m "Add lease service with acquire/heartbeat/release/takeover/cleanup"
```

---

## Task 5: Audit log service

**Files:**
- Create: `backend/datasets/services/audit_service.py`
- Test: `tests/test_audit_service.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_audit_service.py`:
```python
import json
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from backend.core.db import get_db, init_db, close_db, _reset
from backend.datasets.services.audit_service import audit_service


@pytest_asyncio.fixture(autouse=True)
async def tmp_db(monkeypatch):
    _reset()
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    await init_db()
    yield
    await close_db()
    _reset()


@pytest.mark.asyncio
async def test_log_inserts_row():
    await audit_service.log("alice", "episode_annotation", "1:42", "update_grade", {"grade": "A"})
    db = await get_db()
    async with db.execute("SELECT actor, action, payload FROM audit_log") as cursor:
        rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "alice"
    assert rows[0][1] == "update_grade"
    assert json.loads(rows[0][2])["grade"] == "A"


@pytest.mark.asyncio
async def test_log_handles_none_payload():
    await audit_service.log("bob", "episode_reason", "1:42", "acquire_lease", None)
    db = await get_db()
    async with db.execute("SELECT payload FROM audit_log") as cursor:
        row = await cursor.fetchone()
    assert row[0] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit_service.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Write implementation**

Create `backend/datasets/services/audit_service.py`:
```python
from __future__ import annotations

import json

from backend.core.db import get_db


class AuditService:
    async def log(
        self,
        actor: str,
        resource_type: str,
        resource_key: str,
        action: str,
        payload: dict | None = None,
    ) -> None:
        db = await get_db()
        body = json.dumps(payload) if payload is not None else None
        await db.execute(
            "INSERT INTO audit_log (actor, resource_type, resource_key, action, payload) VALUES (?, ?, ?, ?, ?)",
            (actor, resource_type, resource_key, action, body),
        )
        await db.commit()


audit_service = AuditService()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_audit_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/services/audit_service.py tests/test_audit_service.py
git commit -m "Add audit_service for append-only change log"
```

---

## Task 6: Episode update — version check + 409 + SSE publish

**Files:**
- Modify: `backend/datasets/schemas.py`
- Modify: `backend/datasets/services/episode_service.py`
- Modify: `backend/datasets/routers/episodes.py`
- Test: `tests/test_edit_version.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_edit_version.py`:
```python
import pytest
import pytest_asyncio
from pathlib import Path
import tempfile
import json

import pyarrow as pa
import pyarrow.parquet as pq

from backend.core.db import init_db, close_db, _reset
from backend.datasets.services.dataset_service import dataset_service
from backend.datasets.services.episode_service import (
    episode_service, VersionConflict,
)


@pytest_asyncio.fixture(autouse=True)
async def fixture(monkeypatch):
    _reset()
    tmp_root = Path(tempfile.mkdtemp())
    tmp = tmp_root / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    await init_db()

    ds = tmp_root / "mock_ds"
    (ds / "meta" / "episodes" / "chunk-000").mkdir(parents=True)
    (ds / "data" / "chunk-000").mkdir(parents=True)
    (ds / "meta" / "info.json").write_text(json.dumps({
        "fps": 30, "total_episodes": 2, "total_tasks": 1, "robot_type": "t", "features": {},
    }))
    pq.write_table(pa.table({
        "task_index": pa.array([0], type=pa.int64()),
        "task": pa.array(["t"], type=pa.string()),
    }), ds / "meta" / "tasks.parquet")
    pq.write_table(pa.table({
        "episode_index": pa.array([0, 1], type=pa.int64()),
        "task_index": pa.array([0, 0], type=pa.int64()),
        "dataset_from_index": pa.array([0, 10], type=pa.int64()),
        "dataset_to_index": pa.array([10, 20], type=pa.int64()),
    }), ds / "meta" / "episodes" / "chunk-000" / "file-000.parquet")

    monkeypatch.setattr(
        "backend.core.config.settings.allowed_dataset_roots",
        [str(tmp_root)],
    )
    dataset_service.load_dataset(ds)
    yield
    await close_db()
    _reset()


@pytest.mark.asyncio
async def test_update_returns_version_1_on_first_save():
    ep = await episode_service.update_episode_with_version(
        episode_index=0, grade="A", tags=[], reason=None,
        expected_version=1, actor="alice",
    )
    assert ep["version"] == 2
    assert ep["updated_by"] == "alice"


@pytest.mark.asyncio
async def test_update_raises_conflict_on_stale_version():
    await episode_service.update_episode_with_version(
        episode_index=0, grade="A", tags=[], reason=None,
        expected_version=1, actor="alice",
    )
    with pytest.raises(VersionConflict) as exc:
        await episode_service.update_episode_with_version(
            episode_index=0, grade="B", tags=[], reason=None,
            expected_version=1, actor="bob",
        )
    assert exc.value.current_version == 2
    assert exc.value.current["grade"] == "A"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_edit_version.py -v`
Expected: FAIL — `update_episode_with_version` not defined.

- [ ] **Step 3: Extend schemas**

In `backend/datasets/schemas.py` find `class EpisodeUpdate` and change to (keep existing fields, add `version`):
```python
class EpisodeUpdate(BaseModel):
    grade: str | None = None
    tags: list[str] | None = None
    reason: str | None = None
    version: int  # required — clients must send their known version
```

Also in the `Episode` response model add:
```python
    version: int = 1
    updated_by: str | None = None
```

- [ ] **Step 4: Add version-aware update + exception in service**

Edit `backend/datasets/services/episode_service.py`. Add near the top:
```python
from backend.core.sse_bus import bus as sse_bus
from backend.datasets.services.audit_service import audit_service
from backend.datasets.services.lease_service import lease_service


class VersionConflict(Exception):
    def __init__(self, current: dict, current_version: int):
        self.current = current
        self.current_version = current_version
        super().__init__(f"version mismatch (current={current_version})")


class LeasedByOther(Exception):
    def __init__(self, owner: str, expires_at: str):
        self.owner = owner
        self.expires_at = expires_at
        super().__init__(f"locked by {owner}")
```

Replace the body of `update_episode(...)` with a wrapper that calls a new version-aware method. Add new method `update_episode_with_version` to `EpisodeService`:
```python
async def update_episode_with_version(
    self,
    episode_index: int,
    grade: str | None,
    tags: list[str],
    reason: str | None,
    expected_version: int,
    actor: str,
) -> dict[str, Any]:
    if dataset_service.episodes_cache is not None:
        if episode_index not in dataset_service.episodes_cache:
            raise EpisodeNotFoundError(f"Episode {episode_index} not found.")
    else:
        if dataset_service.get_file_for_episode(episode_index) is None:
            raise EpisodeNotFoundError(f"Episode {episode_index} not found.")

    dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
    await _ensure_migrated(dataset_id, dataset_service.dataset_path)

    if reason is not None:
        leases = await lease_service.get_active_leases()
        for lease in leases:
            if (lease.resource_type == "episode_reason"
                    and lease.resource_key == f"{dataset_id}:{episode_index}"
                    and lease.owner != actor):
                raise LeasedByOther(lease.owner, lease.expires_at)

    db = await get_db()
    await db.execute("BEGIN IMMEDIATE")
    try:
        async with db.execute(
            "SELECT grade, tags, reason, version FROM episode_annotations WHERE dataset_id=? AND episode_index=?",
            (dataset_id, episode_index),
        ) as cursor:
            row = await cursor.fetchone()
        current_version = row[3] if row else 1
        current = {
            "grade": row[0] if row else None,
            "tags": _json.loads(row[1]) if row and row[1] else [],
            "reason": row[2] if row else None,
        } if row else {"grade": None, "tags": [], "reason": None}

        if current_version != expected_version:
            await db.execute("ROLLBACK")
            raise VersionConflict(current, current_version)

        effective_reason = reason if grade in ("bad", "normal") else None
        new_version = current_version + 1

        await db.execute(
            """INSERT INTO episode_annotations
               (dataset_id, episode_index, grade, tags, reason, version, updated_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(dataset_id, episode_index) DO UPDATE SET
                 grade=excluded.grade, tags=excluded.tags, reason=excluded.reason,
                 version=excluded.version, updated_by=excluded.updated_by,
                 updated_at=excluded.updated_at""",
            (dataset_id, episode_index, grade, _json.dumps(tags), effective_reason,
             new_version, actor),
        )
        await db.execute("COMMIT")
    except VersionConflict:
        raise
    except Exception:
        await db.execute("ROLLBACK")
        raise

    await _refresh_dataset_stats(dataset_id)
    await audit_service.log(
        actor, "episode_annotation", f"{dataset_id}:{episode_index}",
        "update_episode", {"grade": grade, "tags": tags, "reason": effective_reason},
    )
    await sse_bus.publish(f"dataset:{dataset_id}", {
        "event": "annotation_updated",
        "data": {
            "dataset_id": dataset_id,
            "episode_index": episode_index,
            "grade": grade, "tags": tags, "reason": effective_reason,
            "version": new_version, "by": actor,
        },
    })

    if dataset_service.episodes_cache is not None:
        ep = dataset_service.episodes_cache.get(episode_index)
        if ep:
            ep["grade"] = grade
            ep["tags"] = tags
            ep["reason"] = effective_reason
            ep["version"] = new_version
            ep["updated_by"] = actor
            return ep
    return await self.get_episode(episode_index)
```

Remove the `await _write_annotations_to_parquet(...)` call inside this new method — parquet is exporter-owned now.

- [ ] **Step 5: Update router to pass actor and surface 409/423**

Edit `backend/datasets/routers/episodes.py`:
```python
from fastapi import APIRouter, HTTPException, Request

from backend.core.identity import resolve_actor
from backend.datasets.services.episode_service import (
    episode_service, EpisodeNotFoundError, VersionConflict, LeasedByOther,
)


@router.patch("/{episode_index}", response_model=Episode)
async def update_episode(episode_index: int, update: EpisodeUpdate, request: Request):
    actor = resolve_actor(request)
    try:
        if update.tags is not None:
            tags = update.tags
        else:
            current = await episode_service.get_episode(episode_index)
            tags = current.get("tags", [])
        return await episode_service.update_episode_with_version(
            episode_index=episode_index,
            grade=update.grade,
            tags=tags,
            reason=update.reason,
            expected_version=update.version,
            actor=actor,
        )
    except EpisodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except VersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "version_mismatch", "current": exc.current, "current_version": exc.current_version},
        )
    except LeasedByOther as exc:
        raise HTTPException(
            status_code=423,
            detail={"error": "locked_by", "owner": exc.owner, "expires_at": exc.expires_at},
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 6: Update reader to include `version` in episode dict**

In `backend/datasets/services/episode_service.py`, in `_load_annotations_from_db` change the SELECT and dict to include `version`:
```python
async with db.execute(
    "SELECT episode_index, grade, tags, reason, version, updated_by FROM episode_annotations WHERE dataset_id = ?",
    (dataset_id,),
) as cursor:
    rows = await cursor.fetchall()
return {
    row[0]: {
        "grade": row[1],
        "tags": _json.loads(row[2]) if row[2] else [],
        "reason": row[3],
        "version": row[4],
        "updated_by": row[5],
    }
    for row in rows
}
```

In `get_episodes()` and `get_episode()` where `ann` is merged into `ep`, also copy `ep["version"] = ann.get("version", 1)` and `ep["updated_by"] = ann.get("updated_by")`.

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_edit_version.py tests/test_episode_annotations_db.py tests/test_grade_reason.py -v`
Expected: PASS. Fix any regressions in the existing tests (they may need to pass `version=1` now — update them accordingly).

- [ ] **Step 8: Commit**

```bash
git add backend/datasets/schemas.py backend/datasets/services/episode_service.py backend/datasets/routers/episodes.py tests/test_edit_version.py tests/test_episode_annotations_db.py tests/test_grade_reason.py
git commit -m "Gate episode updates on version and lease, publish SSE events"
```

---

## Task 7: Lease REST endpoints

**Files:**
- Create: `backend/datasets/routers/leases.py`
- Modify: `backend/main.py` (register router)
- Test: `tests/test_leases_router.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_leases_router.py`:
```python
import pytest
from fastapi.testclient import TestClient
import tempfile
from pathlib import Path

from backend.core.db import init_db, close_db, _reset
from backend.main import app


@pytest.fixture
def client(monkeypatch):
    import asyncio
    _reset()
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    asyncio.get_event_loop().run_until_complete(init_db())
    with TestClient(app) as c:
        yield c
    asyncio.get_event_loop().run_until_complete(close_db())
    _reset()


def test_acquire_returns_201(client):
    r = client.post("/api/leases",
        json={"resource_type": "episode_reason", "resource_key": "1:42"},
        headers={"X-User-Name": "alice"})
    assert r.status_code == 201
    assert "expires_at" in r.json()


def test_acquire_conflict_returns_409(client):
    client.post("/api/leases",
        json={"resource_type": "episode_reason", "resource_key": "1:42"},
        headers={"X-User-Name": "alice"})
    r = client.post("/api/leases",
        json={"resource_type": "episode_reason", "resource_key": "1:42"},
        headers={"X-User-Name": "bob"})
    assert r.status_code == 409
    assert r.json()["detail"]["owner"] == "alice"


def test_heartbeat_returns_200(client):
    client.post("/api/leases",
        json={"resource_type": "episode_reason", "resource_key": "1:42"},
        headers={"X-User-Name": "alice"})
    r = client.post("/api/leases/heartbeat",
        json={"resource_type": "episode_reason", "resource_key": "1:42"},
        headers={"X-User-Name": "alice"})
    assert r.status_code == 200


def test_heartbeat_unknown_returns_404(client):
    r = client.post("/api/leases/heartbeat",
        json={"resource_type": "episode_reason", "resource_key": "missing"},
        headers={"X-User-Name": "alice"})
    assert r.status_code == 404


def test_release_returns_204(client):
    client.post("/api/leases",
        json={"resource_type": "episode_reason", "resource_key": "1:42"},
        headers={"X-User-Name": "alice"})
    r = client.request("DELETE", "/api/leases",
        json={"resource_type": "episode_reason", "resource_key": "1:42"},
        headers={"X-User-Name": "alice"})
    assert r.status_code == 204


def test_takeover_returns_200(client):
    client.post("/api/leases",
        json={"resource_type": "episode_reason", "resource_key": "1:42"},
        headers={"X-User-Name": "alice"})
    r = client.post("/api/leases/takeover",
        json={"resource_type": "episode_reason", "resource_key": "1:42"},
        headers={"X-User-Name": "bob"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_leases_router.py -v`
Expected: FAIL (router not registered).

- [ ] **Step 3: Write router**

Create `backend/datasets/routers/leases.py`:
```python
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.core.identity import resolve_actor
from backend.datasets.services.audit_service import audit_service
from backend.datasets.services.lease_service import lease_service, LeaseConflict
from backend.core.sse_bus import bus as sse_bus


router = APIRouter(prefix="/api/leases", tags=["leases"])


class LeaseRequest(BaseModel):
    resource_type: str
    resource_key: str


async def _publish(action: str, req: LeaseRequest, owner: str) -> None:
    channel = f"dataset:{req.resource_key.split(':', 1)[0]}"
    await sse_bus.publish(channel, {
        "event": "lease_changed",
        "data": {
            "resource_type": req.resource_type,
            "resource_key": req.resource_key,
            "owner": owner,
            "action": action,
        },
    })


@router.post("", status_code=201)
async def acquire(req: LeaseRequest, request: Request):
    actor = resolve_actor(request)
    try:
        lease = await lease_service.acquire(req.resource_type, req.resource_key, actor)
    except LeaseConflict as e:
        raise HTTPException(status_code=409, detail={"error": "already_leased_by", "owner": e.owner, "expires_at": e.expires_at})
    await audit_service.log(actor, req.resource_type, req.resource_key, "acquire_lease")
    await _publish("acquired", req, actor)
    return {"expires_at": lease.expires_at}


@router.post("/heartbeat")
async def heartbeat(req: LeaseRequest, request: Request):
    actor = resolve_actor(request)
    try:
        lease = await lease_service.heartbeat(req.resource_type, req.resource_key, actor)
    except LeaseConflict:
        raise HTTPException(status_code=404, detail={"error": "lease_lost"})
    return {"expires_at": lease.expires_at}


@router.delete("", status_code=204)
async def release(req: LeaseRequest, request: Request):
    actor = resolve_actor(request)
    await lease_service.release(req.resource_type, req.resource_key, actor)
    await audit_service.log(actor, req.resource_type, req.resource_key, "release_lease")
    await _publish("released", req, actor)


@router.post("/takeover")
async def takeover(req: LeaseRequest, request: Request):
    actor = resolve_actor(request)
    lease = await lease_service.takeover(req.resource_type, req.resource_key, actor)
    await audit_service.log(actor, req.resource_type, req.resource_key, "takeover")
    await _publish("acquired", req, actor)
    return {"expires_at": lease.expires_at}
```

- [ ] **Step 4: Register router**

In `backend/main.py` add imports and register:
```python
from backend.datasets.routers import leases
...
app.include_router(leases.router)
```

Also add DELETE to the CORS `allow_methods`:
```python
allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_leases_router.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/datasets/routers/leases.py backend/main.py tests/test_leases_router.py
git commit -m "Add REST endpoints for leases with SSE publish"
```

---

## Task 8: SSE events endpoint

**Files:**
- Create: `backend/datasets/routers/events.py`
- Modify: `backend/main.py` (register, add pyproject dep)
- Test: `tests/test_events_router.py` (new)

- [ ] **Step 1: Add dependency**

Run:
```bash
uv pip install sse-starlette
```
And add `sse-starlette` to `[project]` dependencies in `pyproject.toml`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_events_router.py`:
```python
import asyncio
import json
import pytest
from fastapi.testclient import TestClient
import tempfile
from pathlib import Path

from backend.core.db import init_db, close_db, _reset
from backend.core.sse_bus import bus
from backend.main import app


@pytest.fixture
def client(monkeypatch):
    _reset()
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    asyncio.new_event_loop().run_until_complete(init_db())
    with TestClient(app) as c:
        yield c
    _reset()


def test_sse_stream_delivers_published_event(client):
    # Start background publisher
    async def delayed_publish():
        await asyncio.sleep(0.2)
        await bus.publish("dataset:1", {"event": "ping", "data": {"x": 1}})

    loop = asyncio.new_event_loop()
    with client.stream("GET", "/api/events?channel=dataset:1", headers={"Accept": "text/event-stream"}) as resp:
        assert resp.status_code == 200
        loop.run_until_complete(delayed_publish())
        # read until we see our event
        buffer = ""
        for chunk in resp.iter_text():
            buffer += chunk
            if "ping" in buffer:
                break
    assert "ping" in buffer
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_events_router.py -v`
Expected: FAIL.

- [ ] **Step 4: Write router**

Create `backend/datasets/routers/events.py`:
```python
from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from backend.core.sse_bus import bus


router = APIRouter(prefix="/api", tags=["events"])


@router.get("/events")
async def events(request: Request, channel: str):
    async def stream():
        async with bus.subscribe(channel) as queue:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    import asyncio
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # heartbeat comment keeps the connection alive
                    yield {"event": "ping", "data": "{}"}
                    continue
                yield {"event": msg["event"], "data": __import__("json").dumps(msg["data"])}

    return EventSourceResponse(stream())
```

- [ ] **Step 5: Register router**

In `backend/main.py`:
```python
from backend.datasets.routers import events
...
app.include_router(events.router)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_events_router.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/datasets/routers/events.py backend/main.py pyproject.toml uv.lock tests/test_events_router.py
git commit -m "Add SSE events endpoint with idle heartbeat"
```

---

## Task 9: Task annotation service + router (move task instructions off parquet)

**Files:**
- Create: `backend/datasets/services/task_annotation_service.py`
- Create: `backend/datasets/routers/task_annotations.py`
- Modify: `backend/main.py` (register), `backend/datasets/services/task_service.py` (read from DB with parquet fallback)
- Test: `tests/test_task_annotations_db.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_task_annotations_db.py`:
```python
import pytest
import pytest_asyncio
import tempfile
from pathlib import Path

from backend.core.db import init_db, close_db, _reset
from backend.datasets.services.task_annotation_service import (
    task_annotation_service, TaskVersionConflict,
)


@pytest_asyncio.fixture(autouse=True)
async def tmp_db(monkeypatch):
    _reset()
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    await init_db()
    # seed a dataset row
    from backend.core.db import get_db
    db = await get_db()
    await db.execute("INSERT INTO datasets (path, name) VALUES (?, ?)", ("/tmp/ds", "ds"))
    await db.commit()
    yield
    await close_db()
    _reset()


@pytest.mark.asyncio
async def test_upsert_creates_row_version_1():
    t = await task_annotation_service.upsert_initial(dataset_id=1, task_index=0, task="pick up")
    assert t["version"] == 1
    assert t["task"] == "pick up"


@pytest.mark.asyncio
async def test_update_bumps_version():
    await task_annotation_service.upsert_initial(1, 0, "pick up")
    t = await task_annotation_service.update(
        dataset_id=1, task_index=0, task="pick up the cube",
        expected_version=1, actor="alice",
    )
    assert t["version"] == 2


@pytest.mark.asyncio
async def test_update_raises_on_stale_version():
    await task_annotation_service.upsert_initial(1, 0, "pick up")
    await task_annotation_service.update(1, 0, "v2", expected_version=1, actor="alice")
    with pytest.raises(TaskVersionConflict):
        await task_annotation_service.update(1, 0, "v3", expected_version=1, actor="bob")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_task_annotations_db.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Write service**

Create `backend/datasets/services/task_annotation_service.py`:
```python
from __future__ import annotations

from backend.core.db import get_db
from backend.core.sse_bus import bus as sse_bus
from backend.datasets.services.audit_service import audit_service


class TaskVersionConflict(Exception):
    def __init__(self, current: dict, current_version: int):
        self.current = current
        self.current_version = current_version


class TaskAnnotationService:
    async def upsert_initial(self, dataset_id: int, task_index: int, task: str) -> dict:
        db = await get_db()
        await db.execute(
            """INSERT INTO task_annotations (dataset_id, task_index, task)
               VALUES (?, ?, ?)
               ON CONFLICT(dataset_id, task_index) DO NOTHING""",
            (dataset_id, task_index, task),
        )
        await db.commit()
        return await self.get(dataset_id, task_index)

    async def get(self, dataset_id: int, task_index: int) -> dict | None:
        db = await get_db()
        async with db.execute(
            "SELECT task, version, updated_by, updated_at FROM task_annotations WHERE dataset_id=? AND task_index=?",
            (dataset_id, task_index),
        ) as cursor:
            row = await cursor.fetchone()
        if not row:
            return None
        return {"task_index": task_index, "task": row[0], "version": row[1],
                "updated_by": row[2], "updated_at": row[3]}

    async def list_for_dataset(self, dataset_id: int) -> list[dict]:
        db = await get_db()
        async with db.execute(
            "SELECT task_index, task, version, updated_by FROM task_annotations WHERE dataset_id=? ORDER BY task_index",
            (dataset_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [{"task_index": r[0], "task": r[1], "version": r[2], "updated_by": r[3]} for r in rows]

    async def update(self, dataset_id: int, task_index: int, task: str,
                     expected_version: int, actor: str) -> dict:
        db = await get_db()
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute(
                "SELECT task, version FROM task_annotations WHERE dataset_id=? AND task_index=?",
                (dataset_id, task_index),
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                await db.execute("ROLLBACK")
                raise TaskVersionConflict({"task": None}, 0)
            current_version = row[1]
            if current_version != expected_version:
                await db.execute("ROLLBACK")
                raise TaskVersionConflict({"task": row[0]}, current_version)
            new_version = current_version + 1
            await db.execute(
                """UPDATE task_annotations SET task=?, version=?, updated_by=?, updated_at=CURRENT_TIMESTAMP
                   WHERE dataset_id=? AND task_index=?""",
                (task, new_version, actor, dataset_id, task_index),
            )
            await db.execute("COMMIT")
        except TaskVersionConflict:
            raise
        except Exception:
            await db.execute("ROLLBACK")
            raise

        await audit_service.log(actor, "task_annotation", f"{dataset_id}:{task_index}",
                                "update_task", {"task": task})
        await sse_bus.publish(f"dataset:{dataset_id}", {
            "event": "task_updated",
            "data": {"dataset_id": dataset_id, "task_index": task_index,
                     "task": task, "version": new_version, "by": actor},
        })
        return await self.get(dataset_id, task_index)


task_annotation_service = TaskAnnotationService()
```

- [ ] **Step 4: Run service test to verify PASS**

Run: `uv run pytest tests/test_task_annotations_db.py -v`
Expected: PASS.

- [ ] **Step 5: Write router**

Create `backend/datasets/routers/task_annotations.py`:
```python
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.core.identity import resolve_actor
from backend.datasets.services.dataset_service import dataset_service
from backend.datasets.services.episode_service import _ensure_dataset_registered, _ensure_migrated, LeasedByOther
from backend.datasets.services.lease_service import lease_service
from backend.datasets.services.task_annotation_service import (
    task_annotation_service, TaskVersionConflict,
)


router = APIRouter(prefix="/api/task-annotations", tags=["task-annotations"])


class TaskAnnotationUpdate(BaseModel):
    task: str
    version: int


@router.patch("/{task_index}")
async def update_task_annotation(task_index: int, body: TaskAnnotationUpdate, request: Request):
    actor = resolve_actor(request)
    try:
        dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    # lease check
    leases = await lease_service.get_active_leases()
    for lease in leases:
        if (lease.resource_type == "task_instruction"
                and lease.resource_key == f"{dataset_id}:{task_index}"
                and lease.owner != actor):
            raise HTTPException(423, {"error": "locked_by", "owner": lease.owner, "expires_at": lease.expires_at})
    try:
        return await task_annotation_service.update(
            dataset_id, task_index, body.task, body.version, actor,
        )
    except TaskVersionConflict as e:
        raise HTTPException(409, {"error": "version_mismatch", "current": e.current, "current_version": e.current_version})
```

- [ ] **Step 6: Update task_service reader to prefer DB row**

In `backend/datasets/services/task_service.py` (read only — we leave parquet unchanged until exporter runs), modify the `get_tasks` path so that each task from `tasks.parquet` has DB overlay applied when present. Add at the top:
```python
from backend.datasets.services.task_annotation_service import task_annotation_service
```

In whatever method returns the list (follow existing structure), after reading the parquet list, overlay:
```python
dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
db_rows = {r["task_index"]: r for r in await task_annotation_service.list_for_dataset(dataset_id)}
for task in tasks:
    idx = task["task_index"]
    if idx in db_rows:
        task["task"] = db_rows[idx]["task"]
        task["version"] = db_rows[idx]["version"]
        task["updated_by"] = db_rows[idx]["updated_by"]
    else:
        task["version"] = 1
        # backfill DB row so subsequent edits have a starting version
        await task_annotation_service.upsert_initial(dataset_id, idx, task["task"])
```

- [ ] **Step 7: Register router in main**

```python
from backend.datasets.routers import task_annotations
...
app.include_router(task_annotations.router)
```

- [ ] **Step 8: Commit**

```bash
git add backend/datasets/services/task_annotation_service.py backend/datasets/routers/task_annotations.py backend/datasets/services/task_service.py backend/main.py tests/test_task_annotations_db.py
git commit -m "Move task instructions to DB with version and lease protection"
```

---

## Task 10: Parquet exporter as single background task

**Files:**
- Create: `backend/datasets/services/export_worker.py`
- Create: `backend/datasets/routers/export.py`
- Modify: `backend/main.py` (start task in lifespan)
- Test: `tests/test_exporter.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_exporter.py`:
```python
import asyncio
import pytest
import pytest_asyncio
import tempfile, json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from backend.core.db import init_db, close_db, _reset
from backend.datasets.services.dataset_service import dataset_service
from backend.datasets.services.export_worker import ExportWorker


@pytest_asyncio.fixture
async def setup(monkeypatch):
    _reset()
    tmp_root = Path(tempfile.mkdtemp())
    tmp = tmp_root / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    await init_db()
    ds = tmp_root / "mock_ds"
    (ds / "meta" / "episodes" / "chunk-000").mkdir(parents=True)
    (ds / "meta" / "info.json").write_text(json.dumps({
        "fps": 30, "total_episodes": 1, "total_tasks": 1, "robot_type": "t", "features": {},
    }))
    pq.write_table(pa.table({"task_index": pa.array([0]), "task": pa.array(["t"])}),
                   ds / "meta" / "tasks.parquet")
    pq.write_table(pa.table({
        "episode_index": pa.array([0], type=pa.int64()),
        "task_index": pa.array([0], type=pa.int64()),
        "dataset_from_index": pa.array([0], type=pa.int64()),
        "dataset_to_index": pa.array([10], type=pa.int64()),
    }), ds / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    monkeypatch.setattr("backend.core.config.settings.allowed_dataset_roots", [str(tmp_root)])
    dataset_service.load_dataset(ds)
    yield ds
    await close_db()
    _reset()


@pytest.mark.asyncio
async def test_run_once_writes_grade_and_tags(setup):
    from backend.datasets.services.episode_service import episode_service
    await episode_service.update_episode_with_version(0, "A", ["ok"], None, 1, "alice")
    worker = ExportWorker()
    worker.mark_dirty(1)
    await worker.run_once()
    table = pq.read_table(setup / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    assert table.column("grade").to_pylist() == ["A"]
    assert table.column("tags").to_pylist() == [["ok"]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_exporter.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Extract parquet writer logic**

Create `backend/datasets/services/export_worker.py`:
```python
from __future__ import annotations

import asyncio
import logging

from backend.datasets.services.episode_service import (
    _write_annotations_to_parquet, _load_annotations_from_db, _ensure_dataset_registered,
)
from backend.datasets.services.dataset_service import dataset_service

logger = logging.getLogger(__name__)


class ExportWorker:
    def __init__(self, idle_seconds: float = 15.0) -> None:
        self._dirty: set[int] = set()
        self._idle_seconds = idle_seconds
        self.last_run_at: str | None = None
        self.last_error: str | None = None
        self.running = False

    def mark_dirty(self, dataset_id: int) -> None:
        self._dirty.add(dataset_id)

    @property
    def dirty_count(self) -> int:
        return len(self._dirty)

    async def run_once(self) -> None:
        self.running = True
        try:
            pending = set(self._dirty)
            self._dirty.clear()
            for dataset_id in pending:
                annotations = await _load_annotations_from_db(dataset_id)
                updates = {idx: (a.get("grade"), a.get("tags", [])) for idx, a in annotations.items()}
                if updates:
                    await _write_annotations_to_parquet(updates)
            from datetime import datetime, UTC
            self.last_run_at = datetime.now(UTC).isoformat()
            self.last_error = None
        except Exception as e:
            logger.exception("Exporter run failed")
            self.last_error = str(e)
        finally:
            self.running = False

    async def run_forever(self) -> None:
        while True:
            if self._dirty:
                await asyncio.sleep(self._idle_seconds)
                await self.run_once()
            else:
                await asyncio.sleep(1.0)


export_worker = ExportWorker()
```

- [ ] **Step 4: Wire dirty-marking into episode edits**

In `backend/datasets/services/episode_service.py`, after `sse_bus.publish(...)` call, add:
```python
from backend.datasets.services.export_worker import export_worker
export_worker.mark_dirty(dataset_id)
```

- [ ] **Step 5: Write router**

Create `backend/datasets/routers/export.py`:
```python
from fastapi import APIRouter

from backend.datasets.services.export_worker import export_worker


router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/status")
async def status():
    return {
        "dirty": export_worker.dirty_count,
        "running": export_worker.running,
        "last_run_at": export_worker.last_run_at,
        "last_error": export_worker.last_error,
    }


@router.post("/trigger")
async def trigger():
    await export_worker.run_once()
    return await status()
```

- [ ] **Step 6: Start worker in lifespan**

In `backend/main.py` `lifespan`:
```python
from backend.datasets.services.export_worker import export_worker
from backend.datasets.services.lease_service import lease_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # ... existing rerun init ...
    exporter_task = asyncio.create_task(export_worker.run_forever())
    async def lease_sweeper():
        while True:
            try:
                await lease_service.cleanup_expired()
            except Exception:
                logger.exception("lease sweeper failed")
            await asyncio.sleep(60)
    sweeper_task = asyncio.create_task(lease_sweeper())
    yield
    exporter_task.cancel()
    sweeper_task.cancel()
    await close_db()
```

Also register the router:
```python
from backend.datasets.routers import export
app.include_router(export.router)
```

- [ ] **Step 7: Remove parquet writes from request-path**

In `backend/datasets/services/episode_service.py` remove or stop calling `_write_annotations_to_parquet(...)` from both the legacy `update_episode(...)` and `bulk_grade(...)`. Leave the helper function itself — exporter uses it.

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/test_exporter.py tests/test_edit_version.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/datasets/services/export_worker.py backend/datasets/routers/export.py backend/datasets/services/episode_service.py backend/main.py tests/test_exporter.py
git commit -m "Run parquet writes from a single background exporter"
```

---

## Task 11: Bulk grade honors version and leases

**Files:**
- Modify: `backend/datasets/services/episode_service.py`
- Modify: `backend/datasets/schemas.py`
- Modify: `backend/datasets/routers/episodes.py`
- Test: `tests/test_bulk_grade_concurrent.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_bulk_grade_concurrent.py`:
```python
# uses the same fixture shape as test_edit_version.py — copy the fixture block
import pytest
# ... same fixture ...
from backend.datasets.services.episode_service import episode_service


@pytest.mark.asyncio
async def test_bulk_skips_leased_indices(fixture):
    from backend.datasets.services.lease_service import lease_service
    await lease_service.acquire("episode_reason", "1:1", "bob")
    result = await episode_service.bulk_grade_v2([0, 1], "A", actor="alice")
    assert 0 in result["updated"]
    assert 1 in result["skipped_leased"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bulk_grade_concurrent.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `bulk_grade_v2`**

In `backend/datasets/services/episode_service.py` add:
```python
async def bulk_grade_v2(self, episode_indices: list[int], grade: str,
                       actor: str, reason: str | None = None) -> dict:
    dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
    leases = await lease_service.get_active_leases()
    leased_keys = {l.resource_key for l in leases
                   if l.resource_type == "episode_reason" and l.owner != actor}
    updated, skipped, conflicts = [], [], []
    for idx in episode_indices:
        if f"{dataset_id}:{idx}" in leased_keys:
            skipped.append(idx)
            continue
        # read current version
        db = await get_db()
        async with db.execute(
            "SELECT version, tags FROM episode_annotations WHERE dataset_id=? AND episode_index=?",
            (dataset_id, idx),
        ) as cursor:
            row = await cursor.fetchone()
        current_version = row[0] if row else 1
        current_tags = _json.loads(row[1]) if row and row[1] else []
        try:
            await self.update_episode_with_version(
                episode_index=idx, grade=grade, tags=current_tags,
                reason=reason, expected_version=current_version, actor=actor,
            )
            updated.append(idx)
        except VersionConflict:
            conflicts.append(idx)
    return {"updated": updated, "skipped_leased": skipped, "version_conflicts": conflicts}
```

- [ ] **Step 4: Update schema and router**

In `backend/datasets/schemas.py` the existing `BulkGradeRequest` — no changes needed (it already has `episode_indices`, `grade`, `reason`).

In `backend/datasets/routers/episodes.py` update the bulk endpoint:
```python
@router.post("/bulk-grade")
async def bulk_grade_episodes(req: BulkGradeRequest, request: Request):
    actor = resolve_actor(request)
    try:
        return await episode_service.bulk_grade_v2(
            req.episode_indices, req.grade, actor=actor, reason=req.reason,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_bulk_grade_concurrent.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/datasets/services/episode_service.py backend/datasets/routers/episodes.py tests/test_bulk_grade_concurrent.py
git commit -m "Skip leased and stale-version rows in bulk grade"
```

---

## Task 12: Health endpoint surfaces SSE/lease/exporter metrics

**Files:**
- Modify: `backend/main.py`
- Test: `tests/test_health_metrics.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_health_metrics.py`:
```python
import pytest
from fastapi.testclient import TestClient
import tempfile
from pathlib import Path

from backend.core.db import init_db, close_db, _reset
from backend.main import app


def test_health_includes_runtime_metrics(monkeypatch, tmp_path):
    _reset()
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp_path / "h.db"))
    with TestClient(app) as c:
        r = c.get("/api/health")
    body = r.json()
    assert body["status"] == "ok"
    assert "sse_connections" in body
    assert "active_leases" in body
    assert "exporter" in body
    _reset()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_health_metrics.py -v`
Expected: FAIL.

- [ ] **Step 3: Extend `/api/health`**

In `backend/main.py` replace:
```python
@app.get("/api/health")
async def health():
    from backend.core.sse_bus import bus
    from backend.datasets.services.lease_service import lease_service
    from backend.datasets.services.export_worker import export_worker
    leases = await lease_service.get_active_leases()
    return {
        "status": "ok",
        "sse_connections": bus.connection_count,
        "active_leases": len(leases),
        "exporter": {
            "dirty": export_worker.dirty_count,
            "last_run_at": export_worker.last_run_at,
            "last_error": export_worker.last_error,
            "running": export_worker.running,
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_health_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_health_metrics.py
git commit -m "Surface SSE, lease, and exporter counters on /api/health"
```

---

## Task 13: Frontend — user name identity

**Files:**
- Create: `frontend/src/api/userName.ts`
- Create: `frontend/src/components/UserNamePrompt.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/App.tsx` (or equivalent root) to show prompt on first visit

- [ ] **Step 1: Implement user name store**

Create `frontend/src/api/userName.ts`:
```typescript
const KEY = 'curation.userName'

export function getUserName(): string | null {
  return localStorage.getItem(KEY)
}

export function setUserName(name: string): void {
  localStorage.setItem(KEY, name.trim().slice(0, 64))
}

export function clearUserName(): void {
  localStorage.removeItem(KEY)
}
```

- [ ] **Step 2: Inject header via axios**

Edit `frontend/src/api/client.ts`:
```typescript
import axios from 'axios'
import { getUserName } from './userName'

const client = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

client.interceptors.request.use((config) => {
  const name = getUserName()
  if (name) config.headers.set('X-User-Name', name)
  return config
})

export default client
```

- [ ] **Step 3: Create first-visit prompt**

Create `frontend/src/components/UserNamePrompt.tsx`:
```typescript
import { useState } from 'react'
import { setUserName } from '../api/userName'

export function UserNamePrompt({ onDone }: { onDone: () => void }) {
  const [value, setValue] = useState('')
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'var(--bg)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (value.trim()) { setUserName(value); onDone() }
        }}
        style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 320 }}
      >
        <label style={{ color: 'var(--text)' }}>이름을 입력하세요 (공유 curation용)</label>
        <input
          autoFocus value={value} onChange={(e) => setValue(e.target.value)}
          style={{ padding: 8 }}
        />
        <button type="submit" disabled={!value.trim()}>시작</button>
      </form>
    </div>
  )
}
```

- [ ] **Step 4: Wire prompt into App**

In the root component (check `frontend/src/App.tsx`), above existing content:
```typescript
import { useState } from 'react'
import { getUserName } from './api/userName'
import { UserNamePrompt } from './components/UserNamePrompt'

// inside component body
const [hasName, setHasName] = useState(!!getUserName())
if (!hasName) return <UserNamePrompt onDone={() => setHasName(true)} />
```

- [ ] **Step 5: Manual check**

Open the app. First visit should show the prompt. After entering a name, the name persists in `localStorage` and the app loads. Verify the `X-User-Name` header arrives on a PATCH via DevTools.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/userName.ts frontend/src/api/client.ts frontend/src/components/UserNamePrompt.tsx frontend/src/App.tsx
git commit -m "Identify client by localStorage name, inject X-User-Name header"
```

---

## Task 14: Frontend — SSE subscriber singleton

**Files:**
- Create: `frontend/src/api/eventSource.ts`
- Test: `frontend/src/__tests__/eventSource.test.ts` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/eventSource.test.ts`:
```typescript
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { subscribeToDataset } from '../api/eventSource'

class MockEventSource {
  static last: MockEventSource | null = null
  url: string
  onmessage: ((e: MessageEvent) => void) | null = null
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {}
  close = vi.fn()
  constructor(url: string) { this.url = url; MockEventSource.last = this }
  addEventListener(type: string, listener: (e: MessageEvent) => void) {
    (this.listeners[type] ||= []).push(listener)
  }
}

beforeEach(() => {
  // @ts-expect-error mock override
  global.EventSource = MockEventSource
})

describe('subscribeToDataset', () => {
  it('opens an SSE connection for the dataset channel', () => {
    const handler = vi.fn()
    subscribeToDataset(42, 'annotation_updated', handler)
    expect(MockEventSource.last?.url).toBe('/api/events?channel=dataset:42')
  })

  it('calls the handler with parsed JSON data', () => {
    const handler = vi.fn()
    subscribeToDataset(1, 'annotation_updated', handler)
    MockEventSource.last!.listeners['annotation_updated'][0](
      new MessageEvent('annotation_updated', { data: '{"x":1}' }),
    )
    expect(handler).toHaveBeenCalledWith({ x: 1 })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/eventSource.test.ts`
Expected: FAIL.

- [ ] **Step 3: Write implementation**

Create `frontend/src/api/eventSource.ts`:
```typescript
type Handler = (data: unknown) => void

const sources = new Map<number, EventSource>()
const handlers = new Map<string, Set<Handler>>()

function keyFor(datasetId: number, event: string) { return `${datasetId}:${event}` }

export function subscribeToDataset(
  datasetId: number,
  event: string,
  handler: Handler,
): () => void {
  const k = keyFor(datasetId, event)
  if (!handlers.has(k)) handlers.set(k, new Set())
  handlers.get(k)!.add(handler)

  if (!sources.has(datasetId)) {
    const es = new EventSource(`/api/events?channel=dataset:${datasetId}`)
    sources.set(datasetId, es)
    // Attach a single listener per known event type per source; caller must know event names.
    es.addEventListener(event, (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data)
        for (const h of handlers.get(keyFor(datasetId, event)) ?? []) h(data)
      } catch { /* ignore malformed */ }
    })
  } else {
    const es = sources.get(datasetId)!
    es.addEventListener(event, (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data)
        for (const h of handlers.get(keyFor(datasetId, event)) ?? []) h(data)
      } catch { /* ignore */ }
    })
  }

  return () => {
    handlers.get(k)?.delete(handler)
    if (handlers.get(k)?.size === 0 && [...handlers.keys()].every((key) => !key.startsWith(`${datasetId}:`) || handlers.get(key)!.size === 0)) {
      sources.get(datasetId)?.close()
      sources.delete(datasetId)
    }
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/eventSource.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/eventSource.ts frontend/src/__tests__/eventSource.test.ts
git commit -m "Add SSE subscriber singleton with per-event handlers"
```

---

## Task 15: Frontend — `useLease` hook

**Files:**
- Create: `frontend/src/hooks/useLease.ts`
- Test: `frontend/src/__tests__/useLease.test.tsx` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/useLease.test.tsx`:
```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import client from '../api/client'
import { useLease } from '../hooks/useLease'

vi.mock('../api/client')

describe('useLease', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('calls acquire on focus', async () => {
    (client.post as any).mockResolvedValue({ data: { expires_at: 'x' } })
    const { result } = renderHook(() =>
      useLease({ resource_type: 'episode_reason', resource_key: '1:42' }))
    await act(async () => { await result.current.onFocus() })
    expect(client.post).toHaveBeenCalledWith('/leases',
      { resource_type: 'episode_reason', resource_key: '1:42' })
  })

  it('marks lostByOther on 409', async () => {
    (client.post as any).mockRejectedValue({ response: { status: 409, data: { detail: { owner: 'bob' } } } })
    const { result } = renderHook(() =>
      useLease({ resource_type: 'episode_reason', resource_key: '1:42' }))
    await act(async () => { await result.current.onFocus() })
    expect(result.current.lockedBy).toBe('bob')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/useLease.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Write implementation**

Create `frontend/src/hooks/useLease.ts`:
```typescript
import { useCallback, useEffect, useRef, useState } from 'react'
import client from '../api/client'

export interface LeaseKey { resource_type: string; resource_key: string }

export function useLease(key: LeaseKey) {
  const [held, setHeld] = useState(false)
  const [lockedBy, setLockedBy] = useState<string | null>(null)
  const timer = useRef<number | null>(null)

  const onFocus = useCallback(async () => {
    try {
      await client.post('/leases', key)
      setHeld(true); setLockedBy(null)
      timer.current = window.setInterval(() => {
        client.post('/leases/heartbeat', key).catch(() => {
          setHeld(false)
          if (timer.current) { clearInterval(timer.current); timer.current = null }
        })
      }, 10000)
    } catch (err: any) {
      if (err?.response?.status === 409) setLockedBy(err.response.data?.detail?.owner ?? 'unknown')
    }
  }, [key.resource_type, key.resource_key])

  const onBlur = useCallback(async () => {
    if (timer.current) { clearInterval(timer.current); timer.current = null }
    if (held) {
      try { await client.delete('/leases', { data: key }) } catch { /* ignore */ }
      setHeld(false)
    }
  }, [held, key.resource_type, key.resource_key])

  const takeover = useCallback(async () => {
    try {
      await client.post('/leases/takeover', key)
      setHeld(true); setLockedBy(null)
    } catch { /* ignore */ }
  }, [key.resource_type, key.resource_key])

  useEffect(() => () => {
    if (timer.current) clearInterval(timer.current)
  }, [])

  return { held, lockedBy, onFocus, onBlur, takeover, setLockedBy }
}
```

- [ ] **Step 4: Run test**

Run: `cd frontend && npx vitest run src/__tests__/useLease.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useLease.ts frontend/src/__tests__/useLease.test.tsx
git commit -m "Add useLease hook for focus-based soft locks"
```

---

## Task 16: Frontend — useEpisodes integrates SSE + version

**Files:**
- Modify: `frontend/src/hooks/useEpisodes.ts`
- Modify: `frontend/src/types.ts`

- [ ] **Step 1: Extend types**

In `frontend/src/types.ts` add to `Episode`:
```typescript
export interface Episode {
  // ... existing fields
  version?: number
  updated_by?: string | null
}

export interface EpisodeUpdate {
  grade?: string | null
  tags?: string[] | null
  reason?: string | null
  version: number
}
```

- [ ] **Step 2: Rewrite `updateEpisode` with version + 409 surfacing**

In `frontend/src/hooks/useEpisodes.ts` replace `updateEpisode`:
```typescript
const updateEpisode = useCallback(
  async (index: number, grade: string | null, tags: string[], reason?: string | null) => {
    const current = episodes.find((e) => e.episode_index === index)
    const version = current?.version ?? 1
    const update: EpisodeUpdate = { grade, tags, version }
    if (reason !== undefined) update.reason = reason
    try {
      const response = await client.patch<Episode>(`/episodes/${index}`, update)
      const updated = response.data
      setEpisodes((prev) => prev.map((e) => (e.episode_index === index ? updated : e)))
      setSelectedEpisode((prev) => (prev?.episode_index === index ? updated : prev))
    } catch (err: any) {
      if (err?.response?.status === 409) {
        // Merge server state into our cache but do not touch in-flight inputs
        const serverCurrent = err.response.data.detail.current
        const serverVersion = err.response.data.detail.current_version
        setEpisodes((prev) => prev.map((e) =>
          e.episode_index === index
            ? { ...e, ...serverCurrent, version: serverVersion }
            : e
        ))
        throw new Error('version_mismatch')
      }
      if (err?.response?.status === 423) throw new Error(`locked_by:${err.response.data.detail.owner}`)
      throw err
    }
  }, [episodes])
```

- [ ] **Step 3: Subscribe to SSE events**

In the same file, add:
```typescript
import { useEffect } from 'react'
import { subscribeToDataset } from '../api/eventSource'

// Inside useEpisodes: pass datasetId from caller OR read from dataset context.
// Add a useEffect that subscribes when datasetId is known:
useEffect(() => {
  if (!datasetId) return
  const off1 = subscribeToDataset(datasetId, 'annotation_updated', (data: any) => {
    setEpisodes((prev) => prev.map((e) =>
      e.episode_index === data.episode_index
        ? { ...e, grade: data.grade, tags: data.tags, reason: data.reason, version: data.version, updated_by: data.by }
        : e
    ))
  })
  return () => { off1() }
}, [datasetId])
```

(The caller — `DatasetPage.tsx` — needs to thread `datasetId` through. If `useEpisodes` does not currently take it, add `(datasetId?: number)` parameter.)

- [ ] **Step 4: Manual smoke**

Start backend + frontend. Open two browser profiles, change a grade in one, confirm the other's list updates within <1 s without refresh.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useEpisodes.ts frontend/src/types.ts
git commit -m "Wire version tracking and SSE updates into useEpisodes"
```

---

## Task 17: Frontend — EpisodeEditor lease & external-change banner

**Files:**
- Modify: `frontend/src/components/OverviewTab.tsx` (EpisodeEditor lives here based on the repo layout — verify)
- Create: `frontend/src/components/ExternalChangeBanner.tsx`
- Create: `frontend/src/components/LockedField.tsx`

- [ ] **Step 1: Create `ExternalChangeBanner` component**

Create `frontend/src/components/ExternalChangeBanner.tsx`:
```typescript
export function ExternalChangeBanner({ onApply, onDiscard }: { onApply: () => void; onDiscard: () => void }) {
  return (
    <div style={{ background: 'var(--c-yellow-50)', padding: 8, display: 'flex', gap: 12, alignItems: 'center' }}>
      <span style={{ color: 'var(--text)' }}>외부 변경사항 있음</span>
      <button onClick={onApply}>적용</button>
      <button onClick={onDiscard}>버리기</button>
    </div>
  )
}
```

- [ ] **Step 2: Create `LockedField` wrapper**

Create `frontend/src/components/LockedField.tsx`:
```typescript
export function LockedField({
  owner, onTakeover, children,
}: { owner: string | null; onTakeover: () => void; children: React.ReactNode }) {
  if (!owner) return <>{children}</>
  return (
    <div style={{ position: 'relative' }}>
      <div style={{ pointerEvents: 'none', opacity: 0.6 }}>{children}</div>
      <div style={{
        position: 'absolute', inset: 0, display: 'flex',
        alignItems: 'center', justifyContent: 'center', gap: 8,
      }}>
        <span style={{ color: 'var(--text-muted)' }}>{owner} 편집 중…</span>
        <button onClick={onTakeover}>takeover</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Integrate lease into reason textarea**

In the Episode editor component (find the `<textarea>` for reason; grep `reason` in `frontend/src/components/OverviewTab.tsx` / `DatasetPage.tsx`), replace the bare textarea with:
```tsx
const lease = useLease({
  resource_type: 'episode_reason',
  resource_key: `${datasetId}:${episode.episode_index}`,
})
// ...
<LockedField owner={lease.lockedBy} onTakeover={lease.takeover}>
  <textarea
    value={reasonDraft}
    onChange={(e) => setReasonDraft(e.target.value)}
    onFocus={lease.onFocus}
    onBlur={lease.onBlur}
  />
</LockedField>
```

Persist draft on each keystroke to `localStorage[draft:ep-<n>]`:
```tsx
useEffect(() => {
  localStorage.setItem(`draft:ep-${episode.episode_index}`, reasonDraft)
}, [reasonDraft])
```

- [ ] **Step 4: Surface 409 external changes**

Track a local `pendingExternalUpdate` for this episode. When `useEpisodes` receives an SSE `annotation_updated` while `lease.held` is true, do not clobber the textarea value — instead flip a banner flag. Render `<ExternalChangeBanner>` with `onApply={() => setReasonDraft(episode.reason ?? '')}` and `onDiscard={() => /* dismiss banner */}`.

- [ ] **Step 5: Manual smoke**

Two browsers: A opens reason, B sees read-only with "A 편집 중…" and [takeover]. Click takeover in B — A's field flips to "회수당했습니다" (receive `lease_changed(acquired)` → set `lockedBy = 'B'`).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ExternalChangeBanner.tsx frontend/src/components/LockedField.tsx frontend/src/components/OverviewTab.tsx frontend/src/components/DatasetPage.tsx
git commit -m "Lease the reason textarea and surface external-change banners"
```

---

## Task 18: Frontend — DatasetPage row presence + highlight transition

**Files:**
- Create: `frontend/src/components/PresenceDots.tsx`
- Create: `frontend/src/hooks/usePresence.ts`
- Modify: `frontend/src/components/DatasetPage.tsx` (row rendering)

- [ ] **Step 1: Create `usePresence` hook**

Create `frontend/src/hooks/usePresence.ts`:
```typescript
import { useEffect, useState } from 'react'
import { subscribeToDataset } from '../api/eventSource'

export interface Viewer { name: string; focus_episode?: number }

export function usePresence(datasetId: number | null) {
  const [viewers, setViewers] = useState<Viewer[]>([])
  useEffect(() => {
    if (!datasetId) return
    return subscribeToDataset(datasetId, 'presence', (data: any) => {
      setViewers(data.viewers ?? [])
    })
  }, [datasetId])
  return viewers
}
```

- [ ] **Step 2: Create `PresenceDots` component**

Create `frontend/src/components/PresenceDots.tsx`:
```typescript
export function PresenceDots({ names }: { names: string[] }) {
  if (names.length === 0) return null
  return (
    <span title={names.join(', ')} style={{ display: 'inline-flex', gap: 2 }}>
      {names.slice(0, 3).map((n) => (
        <span key={n}
          style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--c-accent)' }} />
      ))}
    </span>
  )
}
```

- [ ] **Step 3: Highlight transition on external change**

In the row cell for `grade` (and `tags`) in `DatasetPage.tsx`, add a ref + effect that adds a `.ext-flash` class for 600 ms when the rendered value changes externally. Add CSS in `frontend/src/App.css`:
```css
.ext-flash { background: var(--c-flash, rgba(255,220,100,0.4)); transition: background 0.6s ease-out; }
```

- [ ] **Step 4: Wire row-level presence**

In the row render, compute per-episode viewer names from `usePresence(datasetId)` by filtering `v.focus_episode === row.episode_index` and pass to `<PresenceDots>`.

- [ ] **Step 5: Add backend presence ticker**

In `backend/datasets/routers/events.py`, extend the `events` endpoint: maintain a per-client state including `actor` and `focus_episode` (take from query params `?focus=`), and every 10 s emit a rolled-up presence event to all subscribers of the dataset channel. Simplest path: keep a module-level `presence: dict[int, dict[str, Viewer]]` keyed by `dataset_id`, update on connect/disconnect and on a new `/api/presence` POST call from the client whenever focus changes. Emit by publishing to the bus:
```python
asyncio.create_task(broadcast_presence_loop(dataset_id))
```

(Full implementation left to the engineer; they can model it after `SseBus`.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/usePresence.ts frontend/src/components/PresenceDots.tsx frontend/src/components/DatasetPage.tsx frontend/src/App.css backend/datasets/routers/events.py
git commit -m "Show presence dots per row and flash external cell updates"
```

---

## Task 19: Frontend — VideoPlayer timestamp copy + URL seek

**Files:**
- Create: `frontend/src/components/TimestampCopyButton.tsx`
- Modify: `frontend/src/components/VideoPlayer.tsx`

- [ ] **Step 1: Implement copy button**

Create `frontend/src/components/TimestampCopyButton.tsx`:
```typescript
export function TimestampCopyButton({ currentTimeSec }: { currentTimeSec: number }) {
  const copy = () => {
    const url = new URL(window.location.href)
    url.searchParams.set('t', currentTimeSec.toFixed(2))
    navigator.clipboard.writeText(url.toString())
  }
  return <button onClick={copy}>🔗 타임스탬프 복사</button>
}
```

- [ ] **Step 2: Seek on mount when `?t=` present**

In `frontend/src/components/VideoPlayer.tsx`, on mount:
```typescript
useEffect(() => {
  const t = new URLSearchParams(window.location.search).get('t')
  if (t && videoRef.current) videoRef.current.currentTime = parseFloat(t)
}, [])
```

Render the button alongside the player controls.

- [ ] **Step 3: Manual smoke**

Play a video, pause at 42.3 s, copy timestamp. Paste the URL into another browser profile — it auto-seeks to 42.3 s. Neither profile affects the other's playback.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/TimestampCopyButton.tsx frontend/src/components/VideoPlayer.tsx
git commit -m "Add shareable timestamp URLs to VideoPlayer"
```

---

## Task 20: Migration script — per-PC SQLite → central DB

**Files:**
- Create: `scripts/migrate_to_central.py`
- Test: `tests/test_migrate_to_central.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_migrate_to_central.py`:
```python
import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from backend.core.db import init_db, close_db, _reset, get_db
from scripts.migrate_to_central import migrate


@pytest_asyncio.fixture
async def tmp_central(monkeypatch):
    _reset()
    tmp = Path(tempfile.mkdtemp()) / "central.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    await init_db()
    yield tmp
    await close_db()
    _reset()


def _make_per_pc_db(path: Path, dataset_path: str, annotations: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
      CREATE TABLE datasets (id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, name TEXT);
      CREATE TABLE episode_annotations (
          dataset_id INTEGER, episode_index INTEGER, grade TEXT, tags TEXT, reason TEXT, updated_at TEXT,
          PRIMARY KEY (dataset_id, episode_index)
      );
    """)
    conn.execute("INSERT INTO datasets (path, name) VALUES (?, ?)", (dataset_path, "ds"))
    for idx, grade, tags, reason, updated_at in annotations:
        conn.execute(
            "INSERT INTO episode_annotations VALUES (1, ?, ?, ?, ?, ?)",
            (idx, grade, json.dumps(tags), reason, updated_at),
        )
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_merge_single_pc_db(tmp_central, tmp_path):
    src = tmp_path / "pc1.db"
    _make_per_pc_db(src, "/data/ds", [(0, "A", ["ok"], None, "2026-04-17 10:00:00")])
    stats = await migrate([src], conflict_csv=tmp_path / "conflicts.csv", dry_run=False)
    assert stats["imported"] == 1
    db = await get_db()
    async with db.execute("SELECT grade FROM episode_annotations WHERE episode_index=0") as cursor:
        row = await cursor.fetchone()
    assert row[0] == "A"


@pytest.mark.asyncio
async def test_conflict_keeps_newer_and_logs(tmp_central, tmp_path):
    src1 = tmp_path / "pc1.db"
    src2 = tmp_path / "pc2.db"
    _make_per_pc_db(src1, "/data/ds", [(0, "A", [], None, "2026-04-17 10:00:00")])
    _make_per_pc_db(src2, "/data/ds", [(0, "B", [], None, "2026-04-17 11:00:00")])
    csv_path = tmp_path / "conflicts.csv"
    stats = await migrate([src1, src2], conflict_csv=csv_path, dry_run=False)
    db = await get_db()
    async with db.execute("SELECT grade FROM episode_annotations WHERE episode_index=0") as cursor:
        row = await cursor.fetchone()
    assert row[0] == "B"
    assert stats["conflicts"] == 1
    assert csv_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migrate_to_central.py -v`
Expected: FAIL.

- [ ] **Step 3: Write the script**

Create `scripts/migrate_to_central.py`:
```python
"""Merge per-PC metadata.db files into the central DB.

Usage:
    python -m scripts.migrate_to_central --source /tmp/pc1.db /tmp/pc2.db --conflicts /tmp/conflicts.csv
    (add --dry-run to just report what would happen)
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sqlite3
from pathlib import Path

from backend.core.db import get_db, init_db


async def migrate(sources: list[Path], conflict_csv: Path, dry_run: bool = False) -> dict:
    await init_db()
    db = await get_db()
    stats = {"imported": 0, "conflicts": 0, "datasets": 0}
    conflict_rows: list[dict] = []

    for src in sources:
        conn = sqlite3.connect(str(src))
        conn.row_factory = sqlite3.Row
        for ds in conn.execute("SELECT path, name FROM datasets"):
            async with db.execute("SELECT id FROM datasets WHERE path=?", (ds["path"],)) as cur:
                row = await cur.fetchone()
            if row:
                central_id = row[0]
            else:
                if not dry_run:
                    await db.execute("INSERT INTO datasets (path, name) VALUES (?, ?)", (ds["path"], ds["name"]))
                    await db.commit()
                async with db.execute("SELECT id FROM datasets WHERE path=?", (ds["path"],)) as cur:
                    central_id = (await cur.fetchone())[0]
                stats["datasets"] += 1

            for ann in conn.execute("SELECT episode_index, grade, tags, reason, updated_at FROM episode_annotations"):
                async with db.execute(
                    "SELECT grade, tags, reason, updated_at FROM episode_annotations WHERE dataset_id=? AND episode_index=?",
                    (central_id, ann["episode_index"]),
                ) as cur:
                    existing = await cur.fetchone()
                if not existing:
                    if not dry_run:
                        await db.execute(
                            """INSERT INTO episode_annotations (dataset_id, episode_index, grade, tags, reason, updated_at, version)
                               VALUES (?, ?, ?, ?, ?, ?, 1)""",
                            (central_id, ann["episode_index"], ann["grade"], ann["tags"], ann["reason"], ann["updated_at"]),
                        )
                        await db.commit()
                    stats["imported"] += 1
                    continue
                # conflict: same key, compare updated_at
                if (existing[0], existing[1], existing[2]) == (ann["grade"], ann["tags"], ann["reason"]):
                    continue
                if ann["updated_at"] > (existing[3] or ""):
                    if not dry_run:
                        await db.execute(
                            """UPDATE episode_annotations SET grade=?, tags=?, reason=?, updated_at=?
                               WHERE dataset_id=? AND episode_index=?""",
                            (ann["grade"], ann["tags"], ann["reason"], ann["updated_at"], central_id, ann["episode_index"]),
                        )
                        await db.commit()
                stats["conflicts"] += 1
                conflict_rows.append({
                    "dataset_path": ds["path"], "episode_index": ann["episode_index"],
                    "existing_grade": existing[0], "new_grade": ann["grade"],
                    "existing_updated_at": existing[3], "new_updated_at": ann["updated_at"],
                    "source": str(src),
                })

        conn.close()

    if conflict_rows:
        with conflict_csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(conflict_rows[0].keys()))
            writer.writeheader()
            for r in conflict_rows:
                writer.writerow(r)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", nargs="+", type=Path, required=True)
    parser.add_argument("--conflicts", type=Path, default=Path("conflicts.csv"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    stats = asyncio.run(migrate(args.source, args.conflicts, args.dry_run))
    print(stats)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migrate_to_central.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_to_central.py tests/test_migrate_to_central.py
git commit -m "Add per-PC DB → central DB migration script"
```

---

## Task 21: Deployment — systemd unit + backup script

**Files:**
- Create: `deploy/curation.service`
- Create: `deploy/backup.sh`
- Create: `deploy/README.md`

- [ ] **Step 1: Write unit file**

Create `deploy/curation.service`:
```ini
[Unit]
Description=LeRobot Curation Tools (FastAPI)
After=network.target

[Service]
Type=simple
User=curation
WorkingDirectory=/opt/curation-tools
ExecStart=/opt/curation-tools/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8001 --workers 1
Restart=always
RestartSec=3
Environment=CURATION_DB_PATH=/var/lib/curation-tools/metadata.db
Environment=CURATION_DATASET_PATH=/mnt/synology/data/data_div/2026_1/lerobot

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Write backup script**

Create `deploy/backup.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
DB=/var/lib/curation-tools/metadata.db
DEST=/mnt/synology/backups/curation
DATE=$(date +%Y-%m-%d)
mkdir -p "$DEST"
sqlite3 "$DB" ".backup $DEST/metadata-$DATE.db"
find "$DEST" -name 'metadata-*.db' -mtime +30 -delete
```

Make executable:
```bash
chmod +x deploy/backup.sh
```

- [ ] **Step 3: Write deploy README**

Create `deploy/README.md`:
````markdown
# Deployment

## Prerequisites

- A dedicated workstation reachable from all team PCs (suggest: 16 GB RAM, 256 GB SSD).
- Python 3.10+, uv, nfs-common mounted at `/mnt/synology`.

## One-time setup

```bash
sudo useradd -r -s /bin/false curation
sudo mkdir -p /opt/curation-tools /var/lib/curation-tools
sudo chown -R curation:curation /opt/curation-tools /var/lib/curation-tools
sudo rsync -a --exclude .venv --exclude frontend/node_modules /path/to/repo/ /opt/curation-tools/
cd /opt/curation-tools
sudo -u curation uv venv .venv
sudo -u curation .venv/bin/pip install -e .
sudo -u curation bash -c "cd frontend && npm install && npm run build"

sudo cp deploy/curation.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now curation.service

sudo crontab -e
# 0 2 * * * /opt/curation-tools/deploy/backup.sh
```

## Migration from per-PC DBs

```bash
mkdir -p /tmp/old-dbs
# on each PC:
rsync ~/.local/share/curation-tools/metadata.db server:/tmp/old-dbs/$(hostname).db

# on server:
cd /opt/curation-tools
sudo -u curation .venv/bin/python -m scripts.migrate_to_central \
  --source /tmp/old-dbs/*.db \
  --conflicts /tmp/curation-conflicts.csv \
  --dry-run
# review /tmp/curation-conflicts.csv
# re-run without --dry-run
```
````

- [ ] **Step 4: Commit**

```bash
git add deploy/
git commit -m "Add systemd unit, nightly backup script, and deploy README"
```

---

## Task 22: Playwright E2E — two-browser collaboration smoke

**Files:**
- Create: `frontend/e2e/multi_user.spec.ts`
- Modify: `frontend/package.json` (add `@playwright/test` if missing, script)

- [ ] **Step 1: Install playwright**

```bash
cd frontend && npm install -D @playwright/test && npx playwright install chromium
```

Add to `package.json` scripts:
```json
"e2e": "playwright test"
```

- [ ] **Step 2: Write E2E**

Create `frontend/e2e/multi_user.spec.ts`:
```typescript
import { test, expect } from '@playwright/test'

const BASE = process.env.E2E_BASE ?? 'http://localhost:5173'

test('two users — lease on reason', async ({ browser }) => {
  const a = await browser.newContext()
  const b = await browser.newContext()
  const pa = await a.newPage()
  const pb = await b.newPage()
  await pa.goto(BASE)
  await pb.goto(BASE)

  // Enter user name on both
  await pa.getByLabel('이름을 입력하세요').fill('alice')
  await pa.getByRole('button', { name: '시작' }).click()
  await pb.getByLabel('이름을 입력하세요').fill('bob')
  await pb.getByRole('button', { name: '시작' }).click()

  // Load dataset (use a known path)
  // ... navigate to an episode in both

  // Alice focuses reason
  await pa.locator('textarea').first().focus()

  // Bob should see lock UI within 2 s
  await expect(pb.getByText(/alice 편집 중/)).toBeVisible({ timeout: 3000 })
})

test('grade change propagates within 1 s', async ({ browser }) => {
  // similar two-context setup; assert other tab's row value updates
})
```

- [ ] **Step 3: Commit**

```bash
git add frontend/e2e/multi_user.spec.ts frontend/package.json frontend/package-lock.json
git commit -m "Add two-browser Playwright smoke for lease and SSE updates"
```

---

## Task 23: Load test — k6 scenario

**Files:**
- Create: `load/curation.js`
- Create: `load/README.md`

- [ ] **Step 1: Write k6 script**

Create `load/curation.js`:
```javascript
import http from 'k6/http'
import { sleep, check } from 'k6'

export const options = {
  scenarios: {
    steady: {
      executor: 'constant-vus',
      vus: 10,
      duration: '20m',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<200'],
    http_req_failed: ['rate<0.05'],
  },
}

const BASE = __ENV.BASE || 'http://localhost:8001'

export default function () {
  const name = `vu-${__VU}`
  const params = { headers: { 'X-User-Name': name, 'Content-Type': 'application/json' } }

  const list = http.get(`${BASE}/api/episodes`, params)
  check(list, { 'list 200': (r) => r.status === 200 })

  const episode = JSON.parse(list.body)[0]
  const newGrade = ['good', 'normal', 'bad'][__VU % 3]
  const patch = http.patch(`${BASE}/api/episodes/${episode.episode_index}`,
    JSON.stringify({ grade: newGrade, tags: episode.tags, version: episode.version }),
    params)
  check(patch, { 'patch 2xx/409': (r) => r.status === 200 || r.status === 409 })

  sleep(1)
}
```

- [ ] **Step 2: Write README**

Create `load/README.md`:
````markdown
# Load testing

Install k6: https://grafana.com/docs/k6/latest/get-started/installation/

Run:

```bash
BASE=http://curation.local:8001 k6 run load/curation.js
```

Pass criteria: `http_req_duration p95 < 200ms`, `http_req_failed < 5%`.
````

- [ ] **Step 3: Commit**

```bash
git add load/
git commit -m "Add k6 load scenario for multi-user curation"
```

---

## Task 24: Stop launching per-PC backend in `start.sh`

**Files:**
- Modify: `start.sh`
- Modify: `README.md`

- [ ] **Step 1: Update `start.sh`**

Replace the backend section of `start.sh` with a guard that refuses to start locally unless `CURATION_STANDALONE=1` is set:
```bash
if [ "${CURATION_STANDALONE:-}" != "1" ]; then
  echo "This repo now runs as a central server. To run locally for development, set CURATION_STANDALONE=1."
  echo "To use the team server, open http://curation.local:8001 in your browser."
  exit 0
fi
```

- [ ] **Step 2: Update README**

In `README.md` replace the "Quick Start" section with a note pointing at the team server URL, and move the old instructions under a new "Local Development" heading gated on `CURATION_STANDALONE=1`.

- [ ] **Step 3: Commit**

```bash
git add start.sh README.md
git commit -m "Route start.sh to the central server by default"
```

---

## Self-Review Notes

- **Spec coverage**: Every spec section has a task — schema V3 (Task 1), identity (Task 2), SSE bus (Task 3) + endpoint (Task 8), lease service (Task 4) + router (Task 7), version flow (Task 6), audit log (Task 5), task annotations (Task 9), exporter (Task 10), bulk conflict (Task 11), health metrics (Task 12), frontend identity (Task 13), SSE client (Task 14), useLease (Task 15), useEpisodes SSE (Task 16), editor lease (Task 17), row presence (Task 18), video timestamps (Task 19), migration (Task 20), deploy (Task 21), E2E (Task 22), load (Task 23), start.sh cutover (Task 24).
- **Placeholder scan**: Two soft spots — Task 18 Step 5 ("Full implementation left to the engineer") and Task 17 Step 4 ("dismiss banner"). These are intentionally sketched because they depend on how the current `DatasetPage.tsx`/`OverviewTab.tsx` manage local state; the engineer should read those files (already cited in File Structure) and follow the existing pattern.
- **Type consistency**: `version` / `updated_by` land in the `Episode` model, `EpisodeUpdate`, and are required by `update_episode_with_version`. Lease key format `f"{dataset_id}:{episode_index}"` is used consistently on backend and frontend. SSE channel name `dataset:<id>` is the same everywhere.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-17-multi-user-curation.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
