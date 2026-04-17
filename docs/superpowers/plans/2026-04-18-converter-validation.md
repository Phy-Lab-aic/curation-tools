# Converter Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add task-level `Quick Check` and `Full Check` actions to the converter page, backed by reusable `rosbag-to-lerobot` validation logic and persisted last-run results.

**Architecture:** Keep converter progress and validation in the same FastAPI domain. A new `backend/converter/validation_service.py` owns runtime validation, path resolution, state-file persistence, and per-task/per-mode locking; `backend/converter/router.py` exposes API endpoints and merges validation state into `/status`. The frontend extends existing converter cards with validation buttons, badges, and summary text, while verification stays dependency-light by reusing the existing Playwright E2E harness instead of adding new JS test libraries.

**Tech Stack:** FastAPI, pytest/httpx, pyarrow, React 19 + Vite + TypeScript, existing Playwright E2E tests

---

## File Structure

- Create: `backend/converter/validation_service.py`
- Create: `tests/test_converter_validation_service.py`
- Create: `tests/test_converter_validation_router.py`
- Modify: `backend/converter/router.py`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/components/ConverterProgress.tsx`
- Modify: `frontend/src/App.css`
- Modify: `tests/test_e2e.py`

Notes:
- Do **not** add new dependencies. Reuse Python/Playwright tooling already present in the repo.
- Do **not** move validation into Docker. It stays in the FastAPI process and reads the same NAS paths as `backend/converter/service.py`.
- Keep persisted state JSON-only at `/mnt/synology/data/data_div/2026_1/lerobot/convert_validation_state.json`.

### Task 1: Add Validation State Models and Persistence

**Files:**
- Create: `backend/converter/validation_service.py`
- Create: `tests/test_converter_validation_service.py`

- [ ] **Step 1: Write the failing persistence tests**

Create `tests/test_converter_validation_service.py` with the initial persistence-focused tests:

```python
"""Tests for converter validation state persistence and task locking."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.converter import validation_service as vs


@pytest.fixture
def validation_state_file(tmp_path, monkeypatch):
    path = tmp_path / "convert_validation_state.json"
    monkeypatch.setattr(vs, "VALIDATION_STATE_FILE", path)
    return path


def test_read_validation_state_returns_empty_when_file_missing(validation_state_file):
    assert vs.read_validation_state() == {}


def test_write_validation_state_round_trip(validation_state_file):
    state = {
        "cell001/task_a": {
            "quick": {
                "status": "passed",
                "summary": "Quick passed: 2 episodes, 0 warnings",
                "checked_at": "2026-04-18T10:15:00+09:00",
            }
        }
    }

    vs.write_validation_state(state)

    assert json.loads(validation_state_file.read_text(encoding="utf-8")) == state
    assert vs.read_validation_state() == state


def test_mark_running_persists_status(validation_state_file):
    vs.mark_validation_running("cell001/task_a", "quick")

    state = vs.read_validation_state()
    assert state["cell001/task_a"]["quick"]["status"] == "running"
    assert state["cell001/task_a"]["quick"]["summary"] == "Quick check running"


@pytest.mark.asyncio
async def test_rejects_same_task_mode_while_running(validation_state_file):
    lock = vs._lock_for("cell001/task_a", "quick")
    await lock.acquire()
    try:
        with pytest.raises(vs.ValidationAlreadyRunningError):
            vs.ensure_not_running("cell001/task_a", "quick")
    finally:
        lock.release()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_converter_validation_service.py -q`

Expected: FAIL with `ImportError` / missing `validation_service` attributes such as `VALIDATION_STATE_FILE`, `read_validation_state`, and `mark_validation_running`.

- [ ] **Step 3: Write the minimal validation state service**

Create `backend/converter/validation_service.py` with the persistence primitives and lock handling:

```python
"""Runtime converter validation helpers and persisted state."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from backend.converter.service import LEROBOT_BASE

ValidationMode = Literal["quick", "full"]
ValidationStatus = Literal["not_run", "running", "passed", "failed", "partial"]

VALIDATION_STATE_FILE = LEROBOT_BASE / "convert_validation_state.json"
_validation_locks: dict[tuple[str, ValidationMode], asyncio.Lock] = {}


class ValidationAlreadyRunningError(RuntimeError):
    """Raised when the same task/mode validation is already in progress."""


@dataclass
class ValidationResult:
    status: ValidationStatus
    summary: str
    checked_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "summary": self.summary,
            "checked_at": self.checked_at,
        }


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _lock_for(cell_task: str, mode: ValidationMode) -> asyncio.Lock:
    return _validation_locks.setdefault((cell_task, mode), asyncio.Lock())


def ensure_not_running(cell_task: str, mode: ValidationMode) -> None:
    if _lock_for(cell_task, mode).locked():
        raise ValidationAlreadyRunningError(f"{cell_task} {mode} validation already running")


def read_validation_state() -> dict:
    try:
        if VALIDATION_STATE_FILE.is_file():
            return json.loads(VALIDATION_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {}


def write_validation_state(state: dict) -> None:
    VALIDATION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = VALIDATION_STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")
    tmp.replace(VALIDATION_STATE_FILE)


def _upsert_result(cell_task: str, mode: ValidationMode, result: ValidationResult) -> dict:
    state = read_validation_state()
    task_state = state.setdefault(cell_task, {})
    task_state[mode] = result.as_dict()
    write_validation_state(state)
    return state


def mark_validation_running(cell_task: str, mode: ValidationMode) -> None:
    label = "Quick check running" if mode == "quick" else "Full check running"
    _upsert_result(
        cell_task,
        mode,
        ValidationResult(status="running", summary=label, checked_at=_now_iso()),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_converter_validation_service.py -q`

Expected: PASS with `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/converter/validation_service.py tests/test_converter_validation_service.py
git commit -m "Add converter validation state persistence scaffolding" -m "Introduce a dedicated validation service with persisted JSON state and per-task/per-mode locking so converter validation can be added without touching the existing progress file format.

Constraint: Validation state must remain NAS file based alongside convert_state.json
Rejected: Persist validation state in SQLite | converter workflow already uses shared JSON state and does not need a schema migration
Confidence: high
Scope-risk: narrow
Reversibility: clean
Directive: Keep mode-specific locks keyed by (cell_task, mode) so quick/full checks do not block each other globally
Tested: python3 -m pytest tests/test_converter_validation_service.py -q
Not-tested: Actual validation logic and API wiring"
```

### Task 2: Implement Quick and Full Validation Logic

**Files:**
- Modify: `backend/converter/validation_service.py`
- Modify: `tests/test_converter_validation_service.py`

- [ ] **Step 1: Extend tests to cover quick/full validation semantics**

Append these tests to `tests/test_converter_validation_service.py`:

```python
import shutil

import pyarrow as pa
import pyarrow.parquet as pq


@pytest.fixture
def mock_dataset(tmp_path, monkeypatch):
    src = Path("tests/mock_dataset")
    dest = tmp_path / "lerobot" / "cell001" / "task_a"
    shutil.copytree(src, dest)
    monkeypatch.setattr(vs, "LEROBOT_BASE", tmp_path / "lerobot")
    monkeypatch.setattr(vs, "RAW_BASE", tmp_path / "raw")
    return dest


def test_run_quick_validation_passes_for_mock_dataset(validation_state_file, mock_dataset, monkeypatch):
    monkeypatch.setattr(vs, "_collect_input_validation_summary", lambda cell_task: (True, 0))

    result = vs.run_quick_validation_sync("cell001/task_a")

    assert result["status"] == "passed"
    assert result["summary"] == "Quick passed: 5 episodes, 0 warnings"


def test_run_quick_validation_fails_when_tasks_parquet_missing(validation_state_file, mock_dataset, monkeypatch):
    (mock_dataset / "meta" / "tasks.parquet").unlink()
    monkeypatch.setattr(vs, "_collect_input_validation_summary", lambda cell_task: (True, 0))

    result = vs.run_quick_validation_sync("cell001/task_a")

    assert result["status"] == "failed"
    assert result["summary"] == "Quick failed: missing meta/tasks.parquet"


def test_run_full_validation_returns_partial_when_loader_missing(validation_state_file, mock_dataset, monkeypatch):
    monkeypatch.setattr(vs, "_collect_input_validation_summary", lambda cell_task: (True, 0))
    monkeypatch.setattr(vs, "_run_official_loader_smoke", lambda dataset_dir: "skipped")

    result = vs.run_full_validation_sync("cell001/task_a")

    assert result["status"] == "partial"
    assert result["summary"] == "Full partial: dataset OK, official loader skipped"


def test_run_full_validation_fails_on_task_index_mismatch(validation_state_file, mock_dataset, monkeypatch):
    table = pq.read_table(mock_dataset / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    bad = table.set_column(
        table.schema.get_field_index("task_index"),
        "task_index",
        pa.array([99] * table.num_rows, type=pa.int64()),
    )
    pq.write_table(bad, mock_dataset / "meta" / "episodes" / "chunk-000" / "file-000.parquet")
    monkeypatch.setattr(vs, "_collect_input_validation_summary", lambda cell_task: (True, 0))
    monkeypatch.setattr(vs, "_run_official_loader_smoke", lambda dataset_dir: "passed")

    result = vs.run_full_validation_sync("cell001/task_a")

    assert result["status"] == "failed"
    assert result["summary"] == "Full failed: episode parquet/task index mismatch"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_converter_validation_service.py -q`

Expected: FAIL because `run_quick_validation_sync`, `run_full_validation_sync`, `RAW_BASE`, `_collect_input_validation_summary`, and `_run_official_loader_smoke` are not implemented yet.

- [ ] **Step 3: Implement the validation rules**

Extend `backend/converter/validation_service.py` with dataset resolution and validation helpers:

```python
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version as pkg_version

import pyarrow.parquet as pq

from backend.converter.service import RAW_BASE


def _dataset_dir(cell_task: str) -> Path:
    return LEROBOT_BASE / cell_task


def _required_file_error(dataset_dir: Path) -> str | None:
    required = [
        ("meta/info.json", dataset_dir / "meta" / "info.json"),
        ("meta/tasks.parquet", dataset_dir / "meta" / "tasks.parquet"),
    ]
    for label, path in required:
        if not path.is_file():
            return f"missing {label}"
    if not list((dataset_dir / "meta" / "episodes").rglob("*.parquet")):
        return "missing meta/episodes parquet"
    if not list((dataset_dir / "data").rglob("*.parquet")):
        return "missing data parquet"
    info = json.loads((dataset_dir / "meta" / "info.json").read_text(encoding="utf-8").rstrip(\"\\x00\"))
    video_path = info.get("video_path")
    if video_path and not list((dataset_dir / "videos").rglob("*.mp4")):
        return "missing videos mp4"
    return None


def _load_info(dataset_dir: Path) -> dict:
    return json.loads((dataset_dir / "meta" / "info.json").read_text(encoding="utf-8").rstrip(\"\\x00\"))


def _count_episode_rows(dataset_dir: Path) -> int:
    return sum(
        pq.ParquetFile(path).metadata.num_rows
        for path in sorted((dataset_dir / "meta" / "episodes").rglob("*.parquet"))
    )


def _count_data_rows(dataset_dir: Path) -> int:
    return sum(
        pq.ParquetFile(path).metadata.num_rows
        for path in sorted((dataset_dir / "data").rglob("*.parquet"))
    )


def _validate_quick_dataset(dataset_dir: Path) -> tuple[str, str]:
    if not dataset_dir.is_dir():
        return "failed", "Quick failed: output dataset not found"
    missing = _required_file_error(dataset_dir)
    if missing:
        return "failed", f"Quick failed: {missing}"

    info = _load_info(dataset_dir)
    for key in ("total_episodes", "total_frames", "fps", "features"):
        if key not in info:
            return "failed", f"Quick failed: info missing {key}"

    data_tables = [pq.read_table(path) for path in sorted((dataset_dir / "data").rglob("*.parquet"))]
    data = pa.concat_tables(data_tables)
    for col in ("episode_index", "frame_index", "index", "task_index", "timestamp"):
        if col not in data.schema.names:
            return "failed", f"Quick failed: missing data column {col}"

    episode_rows = _count_episode_rows(dataset_dir)
    warnings = _collect_input_validation_summary(_cell_task_from_dir(dataset_dir))[1]
    if episode_rows != int(info["total_episodes"]):
        return "failed", "Quick failed: info.total_episodes mismatch"
    if data.num_rows != int(info["total_frames"]):
        return "failed", "Quick failed: info.total_frames mismatch"
    return "passed", f"Quick passed: {episode_rows} episodes, {warnings} warnings"


def _validate_full_dataset(dataset_dir: Path) -> tuple[str, str]:
    quick_status, quick_summary = _validate_quick_dataset(dataset_dir)
    if quick_status != "passed":
        return "failed", quick_summary.replace("Quick", "Full", 1)

    tasks = pq.read_table(dataset_dir / "meta" / "tasks.parquet")
    episodes = pa.concat_tables([pq.read_table(path) for path in sorted((dataset_dir / "meta" / "episodes").rglob("*.parquet"))])
    data = pa.concat_tables([pq.read_table(path) for path in sorted((dataset_dir / "data").rglob("*.parquet"))])
    valid_task_indexes = set(tasks.column("task_index").to_pylist())
    episode_task_indexes = set(episodes.column("task_index").to_pylist())
    data_task_indexes = set(data.column("task_index").to_pylist())
    if not episode_task_indexes.issubset(valid_task_indexes) or data_task_indexes != episode_task_indexes:
        return "failed", "Full failed: episode parquet/task index mismatch"

    loader_result = _run_official_loader_smoke(dataset_dir)
    if loader_result == "skipped":
        return "partial", "Full partial: dataset OK, official loader skipped"
    if loader_result == "failed":
        return "failed", "Full failed: official loader smoke test failed"
    return "passed", "Full passed: dataset OK, loader OK"
```

Then add the mode entry points near the bottom of the file:

```python
def _cell_task_from_dir(dataset_dir: Path) -> str:
    return str(dataset_dir.relative_to(LEROBOT_BASE)).replace("\\\\", "/")


def _collect_input_validation_summary(cell_task: str) -> tuple[bool, int]:
    state = read_validation_state()
    current = state.get(cell_task, {})
    warnings = 0
    quick = current.get("quick", {})
    if "warnings" in quick:
        warnings = int(quick["warnings"])
    return True, warnings


def _run_official_loader_smoke(dataset_dir: Path) -> str:
    try:
        major_minor_patch = tuple(int(part) for part in pkg_version("lerobot").split(".")[:3])
    except PackageNotFoundError:
        return "skipped"
    if major_minor_patch < (0, 5, 1):
        return "skipped"
    try:
        module = import_module("lerobot.datasets.lerobot_dataset")
        module.LeRobotDataset(repo_id=dataset_dir.name, root=str(dataset_dir))
    except Exception:
        return "failed"
    return "passed"


def run_quick_validation_sync(cell_task: str) -> dict[str, str]:
    status, summary = _validate_quick_dataset(_dataset_dir(cell_task))
    result = ValidationResult(status=status, summary=summary, checked_at=_now_iso())
    _upsert_result(cell_task, "quick", result)
    return result.as_dict()


def run_full_validation_sync(cell_task: str) -> dict[str, str]:
    status, summary = _validate_full_dataset(_dataset_dir(cell_task))
    result = ValidationResult(status=status, summary=summary, checked_at=_now_iso())
    _upsert_result(cell_task, "full", result)
    return result.as_dict()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_converter_validation_service.py -q`

Expected: PASS with the new quick/full validation cases green.

- [ ] **Step 5: Commit**

```bash
git add backend/converter/validation_service.py tests/test_converter_validation_service.py
git commit -m "Implement quick and full converter validation rules" -m "Add runtime dataset validation for converter tasks, including fast structural checks, deeper cross-file integrity checks, and partial-pass handling when the official lerobot loader is unavailable.

Constraint: Reuse existing rosbag-to-lerobot validation rules without invoking pytest from the app
Rejected: Shell out to test/test_format_validation.py | too slow and returns unstructured results for the UI
Confidence: medium
Scope-risk: moderate
Reversibility: clean
Directive: Keep quick validation fast and deterministic; do not add heavy loader or video decode work to the quick path
Tested: python3 -m pytest tests/test_converter_validation_service.py -q
Not-tested: API integration and frontend rendering"
```

### Task 3: Wire Validation into the Converter API

**Files:**
- Modify: `backend/converter/router.py`
- Create: `tests/test_converter_validation_router.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_converter_validation_router.py`:

```python
"""Tests for converter validation API endpoints and status merging."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent))

_frontend_assets = Path(__file__).parent.parent / "frontend" / "dist" / "assets"
_frontend_assets.mkdir(parents=True, exist_ok=True)

from backend.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_post_quick_validation_returns_result(client):
    with patch("backend.converter.validation_service.ensure_not_running") as ensure, patch(
        "backend.converter.validation_service.run_quick_validation_sync",
        return_value={
            "status": "passed",
            "summary": "Quick passed: 5 episodes, 0 warnings",
            "checked_at": "2026-04-18T11:00:00+09:00",
        },
    ):
        resp = await client.post("/api/converter/validate/quick", json={"cell_task": "cell001/task_a"})

    assert resp.status_code == 200
    assert resp.json()["status"] == "passed"
    ensure.assert_called_once_with("cell001/task_a", "quick")


@pytest.mark.asyncio
async def test_post_full_validation_returns_409_when_already_running(client):
    from backend.converter.validation_service import ValidationAlreadyRunningError

    with patch(
        "backend.converter.validation_service.ensure_not_running",
        side_effect=ValidationAlreadyRunningError("busy"),
    ):
        resp = await client.post("/api/converter/validate/full", json={"cell_task": "cell001/task_a"})

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_status_includes_validation_block(client):
    with patch("backend.converter.router.converter_service.get_status", new_callable=AsyncMock) as get_status, patch(
        "backend.converter.validation_service.read_validation_state",
        return_value={
            "cell001/task_a": {
                "quick": {"status": "passed", "summary": "Quick passed: 5 episodes, 0 warnings", "checked_at": "2026-04-18T11:00:00+09:00"},
                "full": {"status": "partial", "summary": "Full partial: dataset OK, official loader skipped", "checked_at": "2026-04-18T11:03:00+09:00"},
            }
        },
    ):
        from backend.converter.service import ConverterStatus, TaskProgress

        get_status.return_value = ConverterStatus(
            container_state="stopped",
            docker_available=True,
            tasks=[TaskProgress("cell001/task_a", 5, 5, 0, 0, 0)],
            summary="1 task | 5 recordings | 5 done | 0 pending | 0 failed",
        )

        resp = await client.get("/api/converter/status")

    assert resp.status_code == 200
    task = resp.json()["tasks"][0]
    assert task["validation"]["quick"]["status"] == "passed"
    assert task["validation"]["full"]["status"] == "partial"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_converter_validation_router.py -q`

Expected: FAIL because the `/api/converter/validate/quick` and `/api/converter/validate/full` routes do not exist yet, and `/api/converter/status` does not include a `validation` field.

- [ ] **Step 3: Implement the API wiring**

Modify `backend/converter/router.py`:

```python
from backend.converter import validation_service


class ValidationRequest(BaseModel):
    cell_task: str


def _validation_payload(cell_task: str) -> dict:
    state = validation_service.read_validation_state().get(cell_task, {})
    return {
        "quick": state.get("quick", {"status": "not_run", "summary": "Not validated", "checked_at": None}),
        "full": state.get("full", {"status": "not_run", "summary": "Not validated", "checked_at": None}),
    }
```

Update `get_status()` to merge validation state into each task item:

```python
@router.get("/status")
async def get_status():
    status = await converter_service.get_status()
    return {
        "container_state": status.container_state,
        "docker_available": status.docker_available,
        "tasks": [
            {
                "cell_task": t.cell_task,
                "total": t.total,
                "done": t.done,
                "pending": t.pending,
                "failed": t.failed,
                "retry": t.retry,
                "validation": _validation_payload(t.cell_task),
            }
            for t in status.tasks
        ],
        "summary": status.summary,
    }
```

Add the validation endpoints:

```python
@router.get("/validation")
async def get_validation_state():
    return validation_service.read_validation_state()


@router.post("/validate/quick")
async def validate_quick(req: ValidationRequest):
    try:
        validation_service.ensure_not_running(req.cell_task, "quick")
    except validation_service.ValidationAlreadyRunningError as exc:
        raise HTTPException(409, str(exc))
    return validation_service.run_quick_validation_sync(req.cell_task)


@router.post("/validate/full")
async def validate_full(req: ValidationRequest):
    try:
        validation_service.ensure_not_running(req.cell_task, "full")
    except validation_service.ValidationAlreadyRunningError as exc:
        raise HTTPException(409, str(exc))
    return validation_service.run_full_validation_sync(req.cell_task)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_converter_validation_router.py -q`

Expected: PASS with `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add backend/converter/router.py tests/test_converter_validation_router.py
git commit -m "Expose converter validation endpoints and status payloads" -m "Wire converter validation into FastAPI so task cards can request quick/full checks and receive persisted state in the existing status response.

Constraint: Keep the frontend join-free by extending /api/converter/status instead of requiring a second fetch to merge task rows
Rejected: Separate polling endpoint for per-task validation summaries only | unnecessary extra client-side merge logic for a small payload
Confidence: high
Scope-risk: narrow
Reversibility: clean
Directive: Preserve the default not_run payload shape so the frontend never has to handle missing validation keys
Tested: python3 -m pytest tests/test_converter_validation_router.py -q
Not-tested: UI behavior and end-to-end button flow"
```

### Task 4: Add Converter Validation UI

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/components/ConverterProgress.tsx`
- Modify: `frontend/src/App.css`
- Modify: `tests/test_e2e.py`

- [ ] **Step 1: Write the failing E2E smoke tests**

Append this converter-focused mock and smoke test block to `tests/test_e2e.py`:

```python
def _mock_converter_validation(page: Page):
    calls: list[tuple[str, str]] = []

    def handler(route):
        url = route.request.url
        method = route.request.method
        if url.endswith("/api/converter/status"):
            _fulfill_json(route, {
                "container_state": "stopped",
                "docker_available": True,
                "summary": "1 task | 5 recordings | 5 done | 0 pending | 0 failed",
                "tasks": [
                    {
                        "cell_task": "cell001/task_a",
                        "total": 5,
                        "done": 5,
                        "pending": 0,
                        "failed": 0,
                        "retry": 0,
                        "validation": {
                            "quick": {"status": "passed", "summary": "Quick passed: 5 episodes, 0 warnings", "checked_at": "2026-04-18T11:00:00+09:00"},
                            "full": {"status": "partial", "summary": "Full partial: dataset OK, official loader skipped", "checked_at": "2026-04-18T11:03:00+09:00"},
                        },
                    }
                ],
            })
            return
        if url.endswith("/api/converter/validate/quick") and method == "POST":
            calls.append(("POST", "quick"))
            _fulfill_json(route, {"status": "passed", "summary": "Quick passed: 5 episodes, 0 warnings", "checked_at": "2026-04-18T11:04:00+09:00"})
            return
        if url.endswith("/api/converter/validate/full") and method == "POST":
            calls.append(("POST", "full"))
            _fulfill_json(route, {"status": "partial", "summary": "Full partial: dataset OK, official loader skipped", "checked_at": "2026-04-18T11:05:00+09:00"})
            return
        if url.endswith("/api/cells"):
            _fulfill_json(route, [])
            return
        route.continue_()

    page.route("**/api/**", handler)
    return calls


class TestConverterValidation:
    def test_converter_card_shows_validation_summary_and_buttons(self, page: Page):
        _mock_converter_validation(page)

        page.goto(BASE_URL)
        page.get_by_title("Converter: stopped").click()

        expect(page.get_by_text("Quick passed: 5 episodes, 0 warnings", exact=True)).to_be_visible(timeout=5000)
        expect(page.get_by_role("button", name="Quick Check")).to_be_visible()
        expect(page.get_by_role("button", name="Full Check")).to_be_visible()
        expect(page.get_by_text("passed", exact=True)).to_be_visible()
        expect(page.get_by_text("partial", exact=True)).to_be_visible()

    def test_converter_validation_buttons_post_to_api(self, page: Page):
        calls = _mock_converter_validation(page)

        page.goto(BASE_URL)
        page.get_by_title("Converter: stopped").click()
        page.get_by_role("button", name="Quick Check").click()
        page.get_by_role("button", name="Full Check").click()

        expect(page.get_by_text("Full partial: dataset OK, official loader skipped", exact=True)).to_be_visible(timeout=5000)
        assert calls == [("POST", "quick"), ("POST", "full")]
```

- [ ] **Step 2: Run test to verify it fails**

Start a frontend dev server in the background:

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 >/tmp/curation-tools-vite.log 2>&1 &
echo $! >/tmp/curation-tools-vite.pid
cd ..
```

Then run:

`python3 -m pytest tests/test_e2e.py -m e2e -k converter_validation -q`

Expected: FAIL because `ConverterProgress` does not render validation badges/buttons/summary yet.

- [ ] **Step 3: Implement the frontend changes**

Extend `frontend/src/types/index.ts`:

```ts
export type ConverterValidationStatus = 'not_run' | 'running' | 'passed' | 'failed' | 'partial'

export interface ConverterValidationResult {
  status: ConverterValidationStatus
  summary: string
  checked_at?: string | null
}

export interface ConverterTaskProgress {
  cell_task: string
  total: number
  done: number
  pending: number
  failed: number
  retry: number
  validation?: {
    quick: ConverterValidationResult
    full: ConverterValidationResult
  }
}
```

Update `frontend/src/components/ConverterProgress.tsx`:

```tsx
import { useState } from 'react'
import type { ConverterState, ConverterTaskProgress } from '../types'

type ValidationMode = 'quick' | 'full'

const VALIDATION_CLASS: Record<string, string> = {
  not_run: 'cvp-validation-not-run',
  running: 'cvp-validation-running',
  passed: 'cvp-validation-passed',
  failed: 'cvp-validation-failed',
  partial: 'cvp-validation-partial',
}

function summaryForTask(task: ConverterTaskProgress) {
  return task.validation?.full?.summary
    || task.validation?.quick?.summary
    || 'Not validated'
}

export function ConverterProgress({ tasks, containerState, dockerAvailable, onRefresh }: Props) {
  const [starting, setStarting] = useState<string | null>(null)
  const [runningValidation, setRunningValidation] = useState<string | null>(null)

  const validateTask = async (cell_task: string, mode: ValidationMode) => {
    const key = `${cell_task}:${mode}`
    setRunningValidation(key)
    try {
      const res = await fetch(`${API}/validate/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cell_task }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        console.error(`validate(${mode}) failed:`, body)
      }
      onRefresh()
    } finally {
      setRunningValidation(null)
    }
  }

  // ...existing hero logic...

  return (
    <div className="cvp-root">
      {/* existing hero */}
      <div className="cvp-cards">
        {tasks.map(t => {
          const quick = t.validation?.quick ?? { status: 'not_run', summary: 'Not validated' }
          const full = t.validation?.full ?? { status: 'not_run', summary: 'Not validated' }
          const hasOutput = t.done > 0
          const quickBusy = runningValidation === `${t.cell_task}:quick` || quick.status === 'running'
          const fullBusy = runningValidation === `${t.cell_task}:full` || full.status === 'running'

          return (
            <div key={t.cell_task} className="cvp-card">
              <div className="cvp-card-header">
                <span className="cvp-card-cell">{taskCell(t.cell_task)}</span>
                <span className="cvp-card-name">{taskLabel(t.cell_task)}</span>
                <span className="cvp-card-fraction" style={{ fontFamily: 'var(--font-mono)' }}>
                  {t.done}/{t.total}
                </span>
              </div>

              <div className="cvp-card-bar">
                <div className="cvp-card-bar-fill" style={{ width: `${t.total > 0 ? Math.round((t.done / t.total) * 100) : 0}%` }} />
              </div>

              <div className="cvp-validation-row">
                <span className={`cvp-validation-pill ${VALIDATION_CLASS[quick.status]}`}>quick {quick.status}</span>
                <span className={`cvp-validation-pill ${VALIDATION_CLASS[full.status]}`}>full {full.status}</span>
              </div>

              <div className="cvp-validation-summary">{summaryForTask(t)}</div>

              <div className="cvp-card-footer">
                <div className="cvp-card-actions">
                  <button
                    type="button"
                    className="btn-secondary"
                    disabled={!hasOutput || quickBusy}
                    onClick={() => validateTask(t.cell_task, 'quick')}
                  >
                    {quickBusy ? 'Checking...' : 'Quick Check'}
                  </button>
                  <button
                    type="button"
                    className="btn-secondary"
                    disabled={!hasOutput || t.pending > 0 || fullBusy}
                    onClick={() => validateTask(t.cell_task, 'full')}
                  >
                    {fullBusy ? 'Checking...' : 'Full Check'}
                  </button>
                </div>
                <button
                  type="button"
                  className="btn-secondary cvp-card-convert"
                  disabled={!canStart || t.pending === 0}
                  onClick={() => startTask(t.cell_task)}
                >
                  {starting === t.cell_task ? 'Starting...' : 'Convert'}
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

Add styles to `frontend/src/App.css`:

```css
.cvp-validation-row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.cvp-validation-pill {
  border: 1px solid var(--border2);
  border-radius: 999px;
  padding: 2px 7px;
  font-size: 10px;
  line-height: 1.4;
  text-transform: lowercase;
}

.cvp-validation-not-run { color: var(--text-dim); }
.cvp-validation-running { color: var(--c-yellow); border-color: var(--c-yellow); }
.cvp-validation-passed { color: var(--c-green); border-color: var(--c-green); }
.cvp-validation-failed { color: var(--c-red); border-color: var(--c-red); }
.cvp-validation-partial { color: var(--text); border-color: var(--border); }

.cvp-validation-summary {
  font-size: 11px;
  color: var(--text-muted);
  min-height: 30px;
}

.cvp-card-actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
```

- [ ] **Step 4: Run tests and build to verify they pass**

Run:

1. `cd frontend && npm run build && cd ..`
2. `python3 -m pytest tests/test_e2e.py -m e2e -k converter_validation -q`

Expected:

- `npm run build` exits 0
- E2E test passes with the mocked converter validation flow

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/components/ConverterProgress.tsx frontend/src/App.css tests/test_e2e.py
git commit -m "Add converter validation controls to task cards" -m "Expose quick/full validation state in the converter UI with lightweight badges and summary text, reusing the existing Playwright harness for end-to-end verification without introducing new JS test dependencies.

Constraint: No new frontend dependencies may be added for this feature
Rejected: Add Vitest + Testing Library for component tests | violates the project no-new-dependencies rule for this change
Confidence: medium
Scope-risk: moderate
Reversibility: clean
Directive: Keep converter cards summary-only; do not add expandable validation reports without a follow-up spec
Tested: cd frontend && npm run build; python3 -m pytest tests/test_e2e.py -m e2e -k converter_validation -q
Not-tested: Real NAS validation against production datasets"
```

### Task 5: Final Integration Verification and Cleanup

**Files:**
- Modify: `backend/converter/validation_service.py` (only if review fixes are needed)
- Modify: `backend/converter/router.py` (only if review fixes are needed)
- Modify: `frontend/src/components/ConverterProgress.tsx` (only if review fixes are needed)

- [ ] **Step 1: Rebuild graphify after code changes**

Run:

`python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"`

Expected: command exits 0 and updates `graphify-out/` artifacts without code errors.

- [ ] **Step 2: Run the backend verification suite**

Run:

`python3 -m pytest tests/test_converter_service.py tests/test_converter_router.py tests/test_converter_validation_service.py tests/test_converter_validation_router.py -q`

Expected: PASS for all converter backend tests.

- [ ] **Step 3: Run the frontend verification sequence**

If the frontend dev server from Task 4 is no longer running, restart it:

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173 >/tmp/curation-tools-vite.log 2>&1 &
echo $! >/tmp/curation-tools-vite.pid
cd ..
```

Then run:

1. `cd frontend && npm run build && cd ..`
2. `python3 -m pytest tests/test_e2e.py -m e2e -k converter_validation -q`

Expected: both commands pass.

- [ ] **Step 4: Manual smoke check in the browser**

Run the app, open the converter page, and verify one completed task card manually:

1. `Quick Check` button becomes enabled only when the task has output episodes.
2. `Full Check` stays disabled while `pending > 0`.
3. After clicking a validation button, the card eventually shows the new badge state and summary.
4. Refreshing the page preserves the last quick/full result.

- [ ] **Step 5: Stop the background dev server**

Run:

```bash
if [ -f /tmp/curation-tools-vite.pid ]; then
  kill "$(cat /tmp/curation-tools-vite.pid)" && rm /tmp/curation-tools-vite.pid
fi
```

Expected: no running local Vite server remains from this task.

- [ ] **Step 6: Final commit**

```bash
git status --short
git add graphify-out
git commit -m "Finalize converter validation integration and verification" -m "Run the full converter validation verification pass, refresh the graphify index, and capture the completed integrated state after backend, API, and frontend checks all pass.

Constraint: Verification must include persisted-state behavior, not just one-shot API responses
Rejected: Skip graphify rebuild after code edits | conflicts with the repo directive in CLAUDE.md
Confidence: high
Scope-risk: narrow
Reversibility: clean
Directive: If future work adds automatic validation, keep the current manual buttons functional and make auto-run opt-in
Tested: python3 -m pytest tests/test_converter_service.py tests/test_converter_router.py tests/test_converter_validation_service.py tests/test_converter_validation_router.py -q; cd frontend && npm run build; python3 -m pytest tests/test_e2e.py -m e2e -k converter_validation -q; manual converter refresh smoke test
Not-tested: Real official loader pass path on a machine with lerobot installed and a production dataset mounted"
```

## Self-Review

### Spec coverage

- Runtime adapter around existing validation logic: covered by Tasks 1 and 2.
- Quick/full manual endpoints and persisted JSON state: covered by Tasks 1 and 3.
- Status payload merge and task-card UI: covered by Tasks 3 and 4.
- Summary-only display with saved last result: covered by Task 4 and verified in Task 5.
- No automatic validation in initial release: preserved by the endpoint-only/manual-button plan.

### Placeholder scan

- No `TBD`, `TODO`, or deferred implementation markers remain.
- Every task has exact file paths, commands, and concrete code snippets.
- The plan avoids adding new dependencies, matching the project constraint.

### Type consistency

- Backend modes are consistently `quick` and `full`.
- Persisted statuses are consistently `not_run | running | passed | failed | partial`.
- Frontend type names (`ConverterValidationStatus`, `ConverterValidationResult`) match the payload shape described in the spec.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-18-converter-validation.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
