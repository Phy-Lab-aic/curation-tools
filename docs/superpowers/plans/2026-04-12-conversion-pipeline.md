# Conversion Pipeline Page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Conversion tab to curation_tools that lets users configure and run rosbag→LeRobot conversion pipelines with auto-watch (watchdog) and manual modes.

**Architecture:** New `conversion_service.py` imports `run_conversion` from rosbag-to-lerobot directly (same env), runs jobs in `ThreadPoolExecutor`, tracks state in-memory. New `conversion.py` router exposes REST + SSE endpoints. Frontend adds a top-level tab switcher and a new `ConversionPage` with `ConfigPanel` (left) and `StatusPanel` (right).

**Tech Stack:** Python watchdog, FastAPI StreamingResponse (SSE), React useState, native EventSource API. No new frontend packages.

---

## File Map

| File | Change |
|------|--------|
| `pyproject.toml` | Add `watchdog>=4.0.0` dependency |
| `conversion_configs/` | New directory — one `{name}.json` per profile (gitignore) |
| `backend/services/conversion_service.py` | New — watchdog, job queue, run_conversion wrapper |
| `backend/routers/conversion.py` | New — REST + SSE endpoints |
| `backend/main.py` | Modify — register router, start/stop watchdog in lifespan |
| `frontend/src/hooks/useConversion.ts` | New — all conversion API calls + SSE |
| `frontend/src/components/conversion/ConfigPanel.tsx` | New — left config panel |
| `frontend/src/components/conversion/StatusPanel.tsx` | New — right status + job panel |
| `frontend/src/components/ConversionPage.tsx` | New — composes left+right panels |
| `frontend/src/App.tsx` | Modify — add page tab bar, conditional render |
| `tests/test_conversion_service.py` | New — service unit tests |
| `tests/test_conversion_router.py` | New — router integration tests |

---

## Task 1: Dependencies + Config Directory

**Files:**
- Modify: `pyproject.toml`
- Create: `conversion_configs/.gitkeep`
- Create: `.gitignore` (or modify if exists)

- [ ] **Step 1: Add watchdog to pyproject.toml**

Edit `pyproject.toml` — add `watchdog` to `dependencies`:

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "pyarrow>=17.0.0",
    "rerun-sdk>=0.22.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "watchdog>=4.0.0",
]
```

- [ ] **Step 2: Install the dependency**

```bash
cd /home/weed/psedulab/curation_tools
pip install watchdog>=4.0.0
```

Expected: `Successfully installed watchdog-...`

- [ ] **Step 3: Create conversion_configs directory**

```bash
mkdir -p conversion_configs
touch conversion_configs/.gitkeep
```

- [ ] **Step 4: Add conversion_configs to .gitignore (keep .gitkeep)**

Check if `.gitignore` exists. If so append; if not create:

```
# Conversion config profiles (user-local, not committed)
conversion_configs/*.json
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml conversion_configs/.gitkeep .gitignore
git commit -m "chore: add watchdog dependency and conversion_configs directory"
```

---

## Task 2: Conversion Service

**Files:**
- Create: `backend/services/conversion_service.py`
- Create: `tests/test_conversion_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_conversion_service.py
import json
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Make sure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.conversion_service import ConversionService, ConversionJob


@pytest.fixture
def tmp_profiles(tmp_path):
    return tmp_path / "conversion_configs"


@pytest.fixture
def svc(tmp_profiles):
    tmp_profiles.mkdir()
    return ConversionService(profiles_dir=tmp_profiles)


def test_save_and_load_profile(svc, tmp_profiles):
    profile = {
        "input_path": "/bags",
        "repo_id": "psedulab/test",
        "output_path": "/mnt/hf/test",
        "task": "test_task",
        "fps": 20,
        "camera_topic_map": {},
        "joint_names": [],
        "state_topic": "/joint_states",
        "action_topics_map": {"leader": "/joint_states"},
        "task_instruction": [],
        "tags": [],
    }
    svc.save_profile("myprofile", profile)
    loaded = svc.load_profile("myprofile")
    assert loaded["task"] == "test_task"
    assert loaded["fps"] == 20


def test_list_profiles(svc):
    svc.save_profile("p1", {"task": "t1"})
    svc.save_profile("p2", {"task": "t2"})
    names = svc.list_profiles()
    assert "p1" in names
    assert "p2" in names


def test_delete_profile(svc):
    svc.save_profile("todel", {"task": "x"})
    svc.delete_profile("todel")
    assert "todel" not in svc.list_profiles()


def test_delete_nonexistent_profile_raises(svc):
    with pytest.raises(FileNotFoundError):
        svc.delete_profile("nope")


def test_initial_watch_state(svc):
    status = svc.get_watch_status()
    assert status["watching"] is False
    assert status["input_path"] is None


def test_job_list_initially_empty(svc):
    jobs = svc.get_jobs()
    assert jobs == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/weed/psedulab/curation_tools
python -m pytest tests/test_conversion_service.py -v 2>&1 | head -30
```

Expected: `ImportError` or `ModuleNotFoundError` — service not yet created.

- [ ] **Step 3: Create the conversion service**

```python
# backend/services/conversion_service.py
"""Conversion pipeline service: watchdog + job queue + rosbag-to-lerobot integration."""
from __future__ import annotations

import json
import logging
import shutil
import sys
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

ROSBAG_SRC = Path("/home/weed/psedulab/rosbag-to-lerobot/src")


def _ensure_rosbag_on_path() -> None:
    rosbag_str = str(ROSBAG_SRC)
    if rosbag_str not in sys.path:
        sys.path.insert(0, rosbag_str)


@dataclass
class ConversionJob:
    id: str
    folder: str
    status: Literal["queued", "converting", "done", "failed"]
    message: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "folder": self.folder,
            "status": self.status,
            "message": self.message,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class ConversionService:
    """Manages conversion profiles, job queue, and optional watchdog."""

    MAX_HISTORY = 100

    def __init__(self, profiles_dir: Path | None = None) -> None:
        if profiles_dir is None:
            profiles_dir = Path(__file__).resolve().parents[2] / "conversion_configs"
        self._profiles_dir = Path(profiles_dir)
        self._profiles_dir.mkdir(parents=True, exist_ok=True)

        self._jobs: list[ConversionJob] = []
        self._queued_folders: set[str] = set()  # deduplication
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1)

        self._watching: bool = False
        self._watch_input_path: Optional[str] = None
        self._observer: Any = None  # watchdog Observer

    # ------------------------------------------------------------------
    # Profile CRUD
    # ------------------------------------------------------------------

    def save_profile(self, name: str, data: dict) -> None:
        path = self._profiles_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_profile(self, name: str) -> dict:
        path = self._profiles_dir / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Profile not found: {name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_profiles(self) -> list[str]:
        return sorted(p.stem for p in self._profiles_dir.glob("*.json"))

    def delete_profile(self, name: str) -> None:
        path = self._profiles_dir / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Profile not found: {name}")
        path.unlink()

    # ------------------------------------------------------------------
    # Job management
    # ------------------------------------------------------------------

    def get_jobs(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in self._jobs]

    def _add_job(self, folder: str) -> Optional[ConversionJob]:
        """Create and queue a job for the given folder. Returns None if duplicate."""
        with self._lock:
            if folder in self._queued_folders:
                return None
            job = ConversionJob(id=str(uuid.uuid4()), folder=folder, status="queued")
            self._jobs.append(job)
            self._queued_folders.add(folder)
            # Cap history
            if len(self._jobs) > self.MAX_HISTORY:
                self._jobs = self._jobs[-self.MAX_HISTORY:]
            return job

    def _update_job(self, job_id: str, **kwargs) -> None:
        with self._lock:
            for j in self._jobs:
                if j.id == job_id:
                    for k, v in kwargs.items():
                        setattr(j, k, v)
                    break

    # ------------------------------------------------------------------
    # Conversion execution
    # ------------------------------------------------------------------

    def _run_job(self, job: ConversionJob, profile: dict) -> None:
        """Blocking: runs in ThreadPoolExecutor."""
        _ensure_rosbag_on_path()
        try:
            from main import run_conversion  # noqa: PLC0415
        except ImportError as exc:
            self._update_job(
                job.id,
                status="failed",
                message=f"Cannot import rosbag-to-lerobot: {exc}",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            with self._lock:
                self._queued_folders.discard(job.folder)
            return

        self._update_job(job.id, status="converting", message="Starting conversion...")

        input_path = Path(profile.get("input_path", ""))
        output_path = profile.get("output_path", "")
        folder_path = input_path / job.folder

        # Write a temporary config JSON that run_conversion can read
        import tempfile, os
        cfg_for_run = {k: v for k, v in profile.items()
                       if k not in ("input_path", "output_path")}
        cfg_for_run["folders"] = [job.folder]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as tmp:
            json.dump(cfg_for_run, tmp)
            tmp_path = tmp.name

        try:
            exit_code = run_conversion(
                config_path=tmp_path,
                input_dir=str(input_path),
                output_dir=output_path,
            )
        except Exception as exc:
            exit_code = 1
            logger.exception("run_conversion raised for folder %s", job.folder)
            self._update_job(
                job.id,
                status="failed",
                message=str(exc),
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
            with self._lock:
                self._queued_folders.discard(job.folder)
            return
        finally:
            os.unlink(tmp_path)

        if exit_code == 0:
            # Move folder to processed/
            processed_dir = input_path / "processed"
            processed_dir.mkdir(exist_ok=True)
            dest = processed_dir / job.folder
            if folder_path.exists():
                shutil.move(str(folder_path), str(dest))
            self._update_job(
                job.id,
                status="done",
                message=f"→ processed/{job.folder}",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        else:
            self._update_job(
                job.id,
                status="failed",
                message=f"run_conversion exited with code {exit_code}",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )

        with self._lock:
            self._queued_folders.discard(job.folder)

    def submit_folder(self, folder: str, profile: dict) -> Optional[str]:
        """Queue a folder for conversion. Returns job_id or None if duplicate."""
        job = self._add_job(folder)
        if job is None:
            return None
        self._executor.submit(self._run_job, job, profile)
        return job.id

    # ------------------------------------------------------------------
    # Watch status
    # ------------------------------------------------------------------

    def get_watch_status(self) -> dict:
        return {
            "watching": self._watching,
            "input_path": self._watch_input_path,
        }

    # ------------------------------------------------------------------
    # Watchdog
    # ------------------------------------------------------------------

    def start_watching(self, profile_name: str) -> None:
        if self._watching:
            self.stop_watching()

        profile = self.load_profile(profile_name)
        input_path = Path(profile.get("input_path", ""))
        if not input_path.exists():
            raise ValueError(f"Input path does not exist: {input_path}")

        from watchdog.observers import Observer
        from watchdog.events import FileCreatedEvent, PatternMatchingEventHandler

        svc = self

        class McapHandler(PatternMatchingEventHandler):
            def __init__(self):
                super().__init__(patterns=["*.mcap"], ignore_directories=False)

            def on_created(self, event: FileCreatedEvent):
                folder = Path(event.src_path).parent
                # Skip processed/ subdirectory
                if folder.name == "processed" or "processed" in folder.parts:
                    return
                folder_name = folder.name
                logger.info("Detected new MCAP in folder: %s", folder_name)
                svc.submit_folder(folder_name, profile)

        observer = Observer()
        observer.schedule(McapHandler(), str(input_path), recursive=True)
        observer.start()

        self._observer = observer
        self._watching = True
        self._watch_input_path = str(input_path)
        logger.info("Watching %s for new MCAP files", input_path)

    def stop_watching(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        self._watching = False
        self._watch_input_path = None
        logger.info("Stopped watching")

    def shutdown(self) -> None:
        self.stop_watching()
        self._executor.shutdown(wait=False)


conversion_service = ConversionService()
```

- [ ] **Step 4: Run tests — expect pass**

```bash
python -m pytest tests/test_conversion_service.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/conversion_service.py tests/test_conversion_service.py
git commit -m "feat: add conversion service with profile management and watchdog"
```

---

## Task 3: Conversion Router

**Files:**
- Create: `backend/routers/conversion.py`
- Create: `tests/test_conversion_router.py`

- [ ] **Step 1: Write failing router tests**

```python
# tests/test_conversion_router.py
import json
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.routers.conversion import router, get_conversion_service
from backend.services.conversion_service import ConversionService


@pytest.fixture
def tmp_svc(tmp_path):
    svc = ConversionService(profiles_dir=tmp_path / "profiles")
    return svc


@pytest.fixture
def client(tmp_svc):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_conversion_service] = lambda: tmp_svc
    return TestClient(app)


def test_list_profiles_empty(client):
    r = client.get("/api/conversion/configs")
    assert r.status_code == 200
    assert r.json() == []


def test_create_and_get_profile(client):
    payload = {
        "name": "myprofile",
        "config": {"task": "test", "fps": 20, "input_path": "/bags",
                   "output_path": "/mnt/out", "repo_id": "org/repo",
                   "camera_topic_map": {}, "joint_names": [],
                   "state_topic": "/js", "action_topics_map": {},
                   "task_instruction": [], "tags": []},
    }
    r = client.post("/api/conversion/configs", json=payload)
    assert r.status_code == 201

    r2 = client.get("/api/conversion/configs/myprofile")
    assert r2.status_code == 200
    assert r2.json()["task"] == "test"


def test_delete_profile(client):
    client.post("/api/conversion/configs",
                json={"name": "todel", "config": {"task": "x"}})
    r = client.delete("/api/conversion/configs/todel")
    assert r.status_code == 204

    r2 = client.get("/api/conversion/configs/todel")
    assert r2.status_code == 404


def test_watch_status_initial(client):
    r = client.get("/api/conversion/watch/status")
    assert r.status_code == 200
    assert r.json()["watching"] is False


def test_get_jobs_empty(client):
    r = client.get("/api/conversion/jobs")
    assert r.status_code == 200
    assert r.json() == []
```

- [ ] **Step 2: Run to confirm fail**

```bash
python -m pytest tests/test_conversion_router.py -v 2>&1 | head -20
```

Expected: `ImportError` — router not yet created.

- [ ] **Step 3: Create the router**

```python
# backend/routers/conversion.py
"""FastAPI router for the rosbag→LeRobot conversion pipeline."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.services.conversion_service import ConversionService, conversion_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversion", tags=["conversion"])


# ---------------------------------------------------------------------------
# Dependency injection (allows test override)
# ---------------------------------------------------------------------------

def get_conversion_service() -> ConversionService:
    return conversion_service


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ProfileCreateRequest(BaseModel):
    name: str
    config: dict[str, Any]


class WatchStartRequest(BaseModel):
    profile_name: str


class RunOnceRequest(BaseModel):
    profile_name: str


class JobResponse(BaseModel):
    id: str
    folder: str
    status: str
    message: str
    created_at: str
    finished_at: str | None = None


# ---------------------------------------------------------------------------
# Profile endpoints
# ---------------------------------------------------------------------------

@router.get("/configs")
async def list_configs(svc: ConversionService = Depends(get_conversion_service)):
    return svc.list_profiles()


@router.post("/configs", status_code=201)
async def create_config(
    req: ProfileCreateRequest,
    svc: ConversionService = Depends(get_conversion_service),
):
    svc.save_profile(req.name, req.config)
    return {"name": req.name}


@router.put("/configs/{name}")
async def update_config(
    name: str,
    req: ProfileCreateRequest,
    svc: ConversionService = Depends(get_conversion_service),
):
    svc.save_profile(name, req.config)
    return {"name": name}


@router.get("/configs/{name}")
async def get_config(
    name: str,
    svc: ConversionService = Depends(get_conversion_service),
):
    try:
        return svc.load_profile(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profile not found: {name}")


@router.delete("/configs/{name}", status_code=204)
async def delete_config(
    name: str,
    svc: ConversionService = Depends(get_conversion_service),
):
    try:
        svc.delete_profile(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profile not found: {name}")


# ---------------------------------------------------------------------------
# Watch endpoints
# ---------------------------------------------------------------------------

@router.get("/watch/status")
async def watch_status(svc: ConversionService = Depends(get_conversion_service)):
    return svc.get_watch_status()


@router.post("/watch/start")
async def start_watch(
    req: WatchStartRequest,
    svc: ConversionService = Depends(get_conversion_service),
):
    try:
        svc.start_watching(req.profile_name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"watching": True}


@router.post("/watch/stop")
async def stop_watch(svc: ConversionService = Depends(get_conversion_service)):
    svc.stop_watching()
    return {"watching": False}


# ---------------------------------------------------------------------------
# Manual run
# ---------------------------------------------------------------------------

@router.post("/run", status_code=202)
async def run_once(
    req: RunOnceRequest,
    svc: ConversionService = Depends(get_conversion_service),
):
    """Scan input_path for all unconverted MCAP folders and queue them."""
    try:
        profile = svc.load_profile(req.profile_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profile not found: {req.profile_name}")

    from pathlib import Path
    input_path = Path(profile.get("input_path", ""))
    if not input_path.exists():
        raise HTTPException(status_code=400, detail=f"Input path does not exist: {input_path}")

    queued = []
    for d in sorted(input_path.iterdir()):
        if d.is_dir() and d.name != "processed" and any(d.glob("*.mcap")):
            job_id = svc.submit_folder(d.name, profile)
            if job_id:
                queued.append({"folder": d.name, "job_id": job_id})

    return {"queued": queued}


# ---------------------------------------------------------------------------
# Job list + SSE stream
# ---------------------------------------------------------------------------

@router.get("/jobs", response_model=list[JobResponse])
async def get_jobs(svc: ConversionService = Depends(get_conversion_service)):
    return svc.get_jobs()


@router.get("/jobs/stream")
async def stream_jobs(svc: ConversionService = Depends(get_conversion_service)):
    """SSE endpoint — sends job list every second."""
    async def event_generator():
        try:
            while True:
                jobs = svc.get_jobs()
                data = json.dumps(jobs)
                yield f"data: {data}\n\n"
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: Run router tests**

```bash
python -m pytest tests/test_conversion_router.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/conversion.py tests/test_conversion_router.py
git commit -m "feat: add conversion router with REST and SSE endpoints"
```

---

## Task 4: Backend Integration (main.py)

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Register router and wire lifespan shutdown**

Edit `backend/main.py`:

```python
# Add to imports at top:
from backend.routers import datasets, episodes, tasks, rerun, videos, scalars, hf_sync, dataset_ops, conversion
from backend.services.conversion_service import conversion_service
```

```python
# In lifespan, after sync_task creation:
    yield

    # Cleanup
    sync_task.cancel()
    conversion_service.shutdown()  # stop watchdog if running
```

```python
# After app.include_router(dataset_ops.router):
app.include_router(conversion.router)
```

Also add PATCH to CORS allowed methods (already has GET, POST, PATCH — verify it's present).

- [ ] **Step 2: Verify server starts without error**

```bash
cd /home/weed/psedulab/curation_tools
python -c "from backend.main import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Smoke test the new endpoints**

```bash
# Start server in background, test, kill
uvicorn backend.main:app --port 8001 &
sleep 2
curl -s http://localhost:8001/api/conversion/configs
curl -s http://localhost:8001/api/conversion/watch/status
curl -s http://localhost:8001/api/conversion/jobs
kill %1
```

Expected: `[]`, `{"watching": false, "input_path": null}`, `[]`

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat: register conversion router and wire shutdown in lifespan"
```

---

## Task 5: Frontend Hook

**Files:**
- Create: `frontend/src/hooks/useConversion.ts`

- [ ] **Step 1: Create the hook**

```typescript
// frontend/src/hooks/useConversion.ts
import { useState, useEffect, useCallback, useRef } from 'react'
import apiClient from '../api/client'

export interface ConversionProfile {
  task: string
  fps: number
  input_path: string
  output_path: string
  repo_id: string
  camera_topic_map: Record<string, string>
  joint_names: string[]
  state_topic: string
  action_topics_map: Record<string, string>
  task_instruction: string[]
  tags: string[]
}

export interface ConversionJob {
  id: string
  folder: string
  status: 'queued' | 'converting' | 'done' | 'failed'
  message: string
  created_at: string
  finished_at: string | null
}

export interface WatchStatus {
  watching: boolean
  input_path: string | null
}

const DEFAULT_PROFILE: ConversionProfile = {
  task: '',
  fps: 20,
  input_path: '',
  output_path: '',
  repo_id: '',
  camera_topic_map: {},
  joint_names: [],
  state_topic: '/joint_states',
  action_topics_map: { leader: '/joint_states' },
  task_instruction: [],
  tags: [],
}

export function useConversion() {
  const [profileNames, setProfileNames] = useState<string[]>([])
  const [selectedProfile, setSelectedProfile] = useState<string | null>(null)
  const [profileData, setProfileData] = useState<ConversionProfile>(DEFAULT_PROFILE)
  const [watchStatus, setWatchStatus] = useState<WatchStatus>({ watching: false, input_path: null })
  const [jobs, setJobs] = useState<ConversionJob[]>([])
  const [mountedRepos, setMountedRepos] = useState<Record<string, string>>({}) // repo_id -> mount_point
  const [saving, setSaving] = useState(false)
  const eventSourceRef = useRef<EventSource | null>(null)

  // Load profiles list
  const fetchProfiles = useCallback(async () => {
    const res = await apiClient.get<string[]>('/conversion/configs')
    setProfileNames(res.data)
  }, [])

  // Load profile content
  const loadProfile = useCallback(async (name: string) => {
    const res = await apiClient.get<ConversionProfile>(`/conversion/configs/${name}`)
    setSelectedProfile(name)
    setProfileData(res.data)
  }, [])

  // Save current profile
  const saveProfile = useCallback(async (name: string) => {
    setSaving(true)
    try {
      if (profileNames.includes(name)) {
        await apiClient.put(`/conversion/configs/${name}`, { name, config: profileData })
      } else {
        await apiClient.post('/conversion/configs', { name, config: profileData })
      }
      setSelectedProfile(name)
      await fetchProfiles()
    } finally {
      setSaving(false)
    }
  }, [profileData, profileNames, fetchProfiles])

  // Delete profile
  const deleteProfile = useCallback(async (name: string) => {
    await apiClient.delete(`/conversion/configs/${name}`)
    if (selectedProfile === name) {
      setSelectedProfile(null)
      setProfileData(DEFAULT_PROFILE)
    }
    await fetchProfiles()
  }, [selectedProfile, fetchProfiles])

  // Watch control
  const fetchWatchStatus = useCallback(async () => {
    const res = await apiClient.get<WatchStatus>('/conversion/watch/status')
    setWatchStatus(res.data)
  }, [])

  const startWatch = useCallback(async (profileName: string) => {
    await apiClient.post('/conversion/watch/start', { profile_name: profileName })
    await fetchWatchStatus()
  }, [fetchWatchStatus])

  const stopWatch = useCallback(async () => {
    await apiClient.post('/conversion/watch/stop')
    await fetchWatchStatus()
  }, [fetchWatchStatus])

  // Manual run
  const runOnce = useCallback(async (profileName: string) => {
    await apiClient.post('/conversion/run', { profile_name: profileName })
  }, [])

  // Mounted repos from hf-sync
  const fetchMountedRepos = useCallback(async () => {
    try {
      const res = await apiClient.get<{ mounted_repos: string[]; mount_details: Record<string, { mount_point: string }> }>('/hf-sync/status')
      const details = res.data.mount_details ?? {}
      const map: Record<string, string> = {}
      for (const [repoId, d] of Object.entries(details)) {
        map[repoId] = d.mount_point ?? ''
      }
      setMountedRepos(map)
    } catch {
      // hf-sync not available — ignore
    }
  }, [])

  // SSE job stream
  useEffect(() => {
    const es = new EventSource('/api/conversion/jobs/stream')
    eventSourceRef.current = es
    es.onmessage = (e) => {
      try {
        setJobs(JSON.parse(e.data))
      } catch { /* ignore parse errors */ }
    }
    return () => {
      es.close()
      eventSourceRef.current = null
    }
  }, [])

  // Initial load
  useEffect(() => {
    void fetchProfiles()
    void fetchWatchStatus()
    void fetchMountedRepos()
  }, [fetchProfiles, fetchWatchStatus, fetchMountedRepos])

  return {
    profileNames,
    selectedProfile,
    profileData,
    setProfileData,
    watchStatus,
    jobs,
    mountedRepos,
    saving,
    loadProfile,
    saveProfile,
    deleteProfile,
    startWatch,
    stopWatch,
    runOnce,
    fetchMountedRepos,
  }
}
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd /home/weed/psedulab/curation_tools/frontend
npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors related to `useConversion.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useConversion.ts
git commit -m "feat: add useConversion hook with profile management and SSE job stream"
```

---

## Task 6: ConfigPanel Component

**Files:**
- Create: `frontend/src/components/conversion/ConfigPanel.tsx`

- [ ] **Step 1: Create ConfigPanel**

```tsx
// frontend/src/components/conversion/ConfigPanel.tsx
import React, { useState } from 'react'
import type { ConversionProfile } from '../../hooks/useConversion'

interface Props {
  profileNames: string[]
  selectedProfile: string | null
  profileData: ConversionProfile
  mountedRepos: Record<string, string>
  saving: boolean
  onProfileSelect: (name: string) => void
  onProfileChange: (data: ConversionProfile) => void
  onSave: (name: string) => void
  onDelete: (name: string) => void
}

export function ConfigPanel({
  profileNames, selectedProfile, profileData, mountedRepos,
  saving, onProfileSelect, onProfileChange, onSave, onDelete,
}: Props) {
  const [newProfileName, setNewProfileName] = useState('')
  const [showNewInput, setShowNewInput] = useState(false)
  const [newCamKey, setNewCamKey] = useState('')
  const [newCamVal, setNewCamVal] = useState('')
  const [newJoint, setNewJoint] = useState('')
  const [newInstruction, setNewInstruction] = useState('')

  const update = (patch: Partial<ConversionProfile>) =>
    onProfileChange({ ...profileData, ...patch })

  const handleRepoSelect = (repoId: string) => {
    const mountPoint = mountedRepos[repoId] ?? ''
    update({ repo_id: repoId, output_path: mountPoint })
  }

  const addCamera = () => {
    if (!newCamKey.trim()) return
    update({
      camera_topic_map: { ...profileData.camera_topic_map, [newCamKey.trim()]: newCamVal.trim() }
    })
    setNewCamKey(''); setNewCamVal('')
  }

  const removeCamera = (key: string) => {
    const m = { ...profileData.camera_topic_map }
    delete m[key]
    update({ camera_topic_map: m })
  }

  const addJoint = () => {
    if (!newJoint.trim()) return
    update({ joint_names: [...profileData.joint_names, newJoint.trim()] })
    setNewJoint('')
  }

  const removeJoint = (j: string) =>
    update({ joint_names: profileData.joint_names.filter(x => x !== j) })

  const addInstruction = () => {
    if (!newInstruction.trim()) return
    update({ task_instruction: [...profileData.task_instruction, newInstruction.trim()] })
    setNewInstruction('')
  }

  const removeInstruction = (i: number) =>
    update({ task_instruction: profileData.task_instruction.filter((_, idx) => idx !== i) })

  const handleSave = () => {
    const name = selectedProfile ?? newProfileName.trim()
    if (!name) { setShowNewInput(true); return }
    onSave(name)
    setShowNewInput(false)
    setNewProfileName('')
  }

  return (
    <div className="conversion-config-panel">
      {/* Profile selector */}
      <div className="conversion-section conversion-profile-bar">
        <label className="conversion-label">Config Profile</label>
        <div className="conversion-profile-row">
          <select
            className="conversion-select"
            value={selectedProfile ?? ''}
            onChange={e => e.target.value && onProfileSelect(e.target.value)}
          >
            <option value="">— select profile —</option>
            {profileNames.map(n => <option key={n} value={n}>{n}</option>)}
          </select>
          <button className="btn-sm" onClick={() => setShowNewInput(v => !v)}>+ New</button>
          {selectedProfile && (
            <button className="btn-sm btn-danger" onClick={() => onDelete(selectedProfile)}>🗑</button>
          )}
        </div>
        {showNewInput && (
          <div className="conversion-new-profile-row">
            <input
              className="conversion-input"
              placeholder="profile name"
              value={newProfileName}
              onChange={e => setNewProfileName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleSave()}
            />
          </div>
        )}
      </div>

      {/* Source */}
      <div className="conversion-section">
        <label className="conversion-label">Source</label>
        <div className="conversion-field">
          <span className="conversion-field-label">Input Path</span>
          <input
            className="conversion-input"
            value={profileData.input_path}
            onChange={e => update({ input_path: e.target.value })}
            placeholder="/path/to/mcap/folders"
          />
        </div>
      </div>

      {/* Target HF repo */}
      <div className="conversion-section">
        <label className="conversion-label">Target HF Repository</label>
        <div className="conversion-repo-list">
          {Object.entries(mountedRepos).map(([repoId, mountPoint]) => (
            <div
              key={repoId}
              className={`conversion-repo-item ${profileData.repo_id === repoId ? 'selected' : ''}`}
              onClick={() => handleRepoSelect(repoId)}
            >
              <span className="conversion-repo-dot mounted" />
              <div>
                <div className="conversion-repo-name">{repoId}</div>
                <div className="conversion-repo-mount">{mountPoint}</div>
              </div>
              {profileData.repo_id === repoId && <span className="conversion-repo-check">✓</span>}
            </div>
          ))}
          <div className="conversion-repo-create" onClick={() => {
            const id = prompt('New repo_id (e.g. org/name):')
            if (id) update({ repo_id: id, output_path: '' })
          }}>
            <span>+</span> 새 저장소 생성
          </div>
        </div>
      </div>

      {/* Config fields */}
      <div className="conversion-section">
        <label className="conversion-label">Config</label>
        <div className="conversion-row-2col">
          <div className="conversion-field">
            <span className="conversion-field-label">Task Name</span>
            <input className="conversion-input" value={profileData.task}
              onChange={e => update({ task: e.target.value })} />
          </div>
          <div className="conversion-field">
            <span className="conversion-field-label">FPS</span>
            <input className="conversion-input" type="number" value={profileData.fps}
              onChange={e => update({ fps: Number(e.target.value) })} style={{ width: 60 }} />
          </div>
        </div>

        {/* Camera Topics */}
        <div className="conversion-field">
          <span className="conversion-field-label">Camera Topics</span>
          {Object.entries(profileData.camera_topic_map).map(([k, v]) => (
            <div key={k} className="conversion-kv-row">
              <input className="conversion-input conversion-key-input" value={k} readOnly />
              <span className="conversion-arrow">→</span>
              <input className="conversion-input" value={v}
                onChange={e => update({ camera_topic_map: { ...profileData.camera_topic_map, [k]: e.target.value } })} />
              <button className="btn-xs btn-danger" onClick={() => removeCamera(k)}>✕</button>
            </div>
          ))}
          <div className="conversion-kv-row">
            <input className="conversion-input conversion-key-input" placeholder="cam_name"
              value={newCamKey} onChange={e => setNewCamKey(e.target.value)} />
            <span className="conversion-arrow">→</span>
            <input className="conversion-input" placeholder="/topic"
              value={newCamVal} onChange={e => setNewCamVal(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addCamera()} />
            <button className="btn-xs" onClick={addCamera}>+</button>
          </div>
        </div>

        {/* Joint Names */}
        <div className="conversion-field">
          <span className="conversion-field-label">Joint Names</span>
          <div className="conversion-tags">
            {profileData.joint_names.map(j => (
              <span key={j} className="conversion-tag">
                {j} <button className="tag-remove" onClick={() => removeJoint(j)}>✕</button>
              </span>
            ))}
            <div className="conversion-tag-input-row">
              <input className="conversion-input conversion-tag-input" placeholder="joint_name"
                value={newJoint} onChange={e => setNewJoint(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addJoint()} />
              <button className="btn-xs" onClick={addJoint}>+</button>
            </div>
          </div>
        </div>

        {/* Task Instructions */}
        <div className="conversion-field">
          <span className="conversion-field-label">Task Instructions</span>
          {profileData.task_instruction.map((inst, i) => (
            <div key={i} className="conversion-kv-row">
              <input className="conversion-input" value={inst}
                onChange={e => {
                  const arr = [...profileData.task_instruction]
                  arr[i] = e.target.value
                  update({ task_instruction: arr })
                }} />
              <button className="btn-xs btn-danger" onClick={() => removeInstruction(i)}>✕</button>
            </div>
          ))}
          <div className="conversion-kv-row">
            <input className="conversion-input" placeholder="Add instruction..."
              value={newInstruction} onChange={e => setNewInstruction(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addInstruction()} />
            <button className="btn-xs" onClick={addInstruction}>+</button>
          </div>
        </div>
      </div>

      {/* Save */}
      <div className="conversion-save-bar">
        <button className="btn-primary" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving...' : '💾 Save Config'}
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /home/weed/psedulab/curation_tools/frontend
npx tsc --noEmit 2>&1 | grep "ConfigPanel" | head -10
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/conversion/ConfigPanel.tsx
git commit -m "feat: add ConversionConfigPanel component"
```

---

## Task 7: StatusPanel Component

**Files:**
- Create: `frontend/src/components/conversion/StatusPanel.tsx`

- [ ] **Step 1: Create StatusPanel**

```tsx
// frontend/src/components/conversion/StatusPanel.tsx
import React from 'react'
import type { ConversionJob, WatchStatus } from '../../hooks/useConversion'

interface Props {
  watchStatus: WatchStatus
  jobs: ConversionJob[]
  selectedProfile: string | null
  onStartWatch: () => void
  onStopWatch: () => void
  onRunOnce: () => void
}

export function StatusPanel({ watchStatus, jobs, selectedProfile, onStartWatch, onStopWatch, onRunOnce }: Props) {
  const activeJobs = jobs.filter(j => j.status === 'queued' || j.status === 'converting')
  const historyJobs = jobs.filter(j => j.status === 'done' || j.status === 'failed')

  return (
    <div className="conversion-status-panel">
      {/* Watch toggle */}
      <div className="conversion-watch-card">
        <div className="conversion-watch-info">
          <div className="conversion-watch-title">Auto Watch Mode</div>
          <div className="conversion-watch-sub">새 MCAP 감지 → 변환 → processed/ 이동</div>
        </div>
        <div className="conversion-watch-toggle">
          <button
            className={`toggle-btn ${watchStatus.watching ? 'active' : ''}`}
            onClick={watchStatus.watching ? onStopWatch : onStartWatch}
            disabled={!selectedProfile && !watchStatus.watching}
          >
            <span className="toggle-knob" />
          </button>
          <span className={`toggle-label ${watchStatus.watching ? 'active' : ''}`}>
            {watchStatus.watching ? 'Watching' : 'Stopped'}
          </span>
        </div>
      </div>

      {/* Manual controls */}
      <div className="conversion-controls">
        <button
          className="btn-secondary conversion-run-btn"
          onClick={onRunOnce}
          disabled={!selectedProfile}
        >
          ▶ Run Once
        </button>
        {watchStatus.watching && (
          <button className="btn-danger-outline" onClick={onStopWatch}>■ Stop</button>
        )}
      </div>

      {/* Active jobs */}
      {activeJobs.length > 0 && (
        <div className="conversion-jobs-section">
          <div className="conversion-jobs-title">Active Jobs</div>
          <div className="conversion-jobs-list">
            {activeJobs.map(job => (
              <div key={job.id} className="conversion-job-item">
                <div className="conversion-job-header">
                  <span className="conversion-job-folder">{job.folder}/</span>
                  <span className={`conversion-job-badge ${job.status}`}>
                    {job.status === 'converting' ? 'Converting' : 'Queued'}
                  </span>
                </div>
                {job.status === 'converting' && (
                  <>
                    <div className="conversion-progress-bar">
                      <div className="conversion-progress-fill indeterminate" />
                    </div>
                    <div className="conversion-job-message">{job.message}</div>
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* History */}
      {historyJobs.length > 0 && (
        <div className="conversion-jobs-section">
          <div className="conversion-jobs-title">Recent History</div>
          <div className="conversion-jobs-list">
            {historyJobs.slice(-20).reverse().map(job => (
              <div key={job.id} className="conversion-job-item history">
                <span className="conversion-job-folder">{job.folder}/</span>
                <div className="conversion-job-outcome">
                  {job.status === 'done' ? (
                    <>
                      <span className="conversion-job-dest">{job.message}</span>
                      <span className="conversion-job-badge done">✓ Done</span>
                    </>
                  ) : (
                    <span className="conversion-job-badge failed" title={job.message}>✗ Failed</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {activeJobs.length === 0 && historyJobs.length === 0 && (
        <div className="conversion-empty">No jobs yet. Start watching or run once.</div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript**

```bash
cd /home/weed/psedulab/curation_tools/frontend
npx tsc --noEmit 2>&1 | grep "StatusPanel" | head -10
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/conversion/StatusPanel.tsx
git commit -m "feat: add ConversionStatusPanel component"
```

---

## Task 8: ConversionPage + App.tsx Tab Navigation

**Files:**
- Create: `frontend/src/components/ConversionPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Create ConversionPage**

```tsx
// frontend/src/components/ConversionPage.tsx
import React from 'react'
import { useConversion } from '../hooks/useConversion'
import { ConfigPanel } from './conversion/ConfigPanel'
import { StatusPanel } from './conversion/StatusPanel'

export function ConversionPage() {
  const {
    profileNames, selectedProfile, profileData, mountedRepos, saving,
    watchStatus, jobs,
    loadProfile, saveProfile, deleteProfile,
    startWatch, stopWatch, runOnce,
    setProfileData,
  } = useConversion()

  const handleStartWatch = () => {
    if (!selectedProfile) return
    void startWatch(selectedProfile)
  }

  const handleRunOnce = () => {
    if (!selectedProfile) return
    void runOnce(selectedProfile)
  }

  return (
    <div className="conversion-page">
      <ConfigPanel
        profileNames={profileNames}
        selectedProfile={selectedProfile}
        profileData={profileData}
        mountedRepos={mountedRepos}
        saving={saving}
        onProfileSelect={loadProfile}
        onProfileChange={setProfileData}
        onSave={saveProfile}
        onDelete={deleteProfile}
      />
      <StatusPanel
        watchStatus={watchStatus}
        jobs={jobs}
        selectedProfile={selectedProfile}
        onStartWatch={handleStartWatch}
        onStopWatch={() => void stopWatch()}
        onRunOnce={handleRunOnce}
      />
    </div>
  )
}
```

- [ ] **Step 2: Modify App.tsx — add tab type and top bar**

At the top of `App.tsx`, add the import and type:

```typescript
import { ConversionPage } from './components/ConversionPage'

type PageType = 'conversion' | 'curation'
```

Inside the `App()` function, add state after existing state declarations:

```typescript
const [activePage, setActivePage] = useState<PageType>('conversion')
```

In the JSX return, wrap the existing content and prepend the tab bar. The return should become:

```tsx
return (
  <div className="app-root">
    <nav className="page-tab-bar">
      <button
        className={`page-tab ${activePage === 'conversion' ? 'active' : ''}`}
        onClick={() => setActivePage('conversion')}
      >
        Conversion
      </button>
      <button
        className={`page-tab ${activePage === 'curation' ? 'active' : ''}`}
        onClick={() => setActivePage('curation')}
      >
        Curation
      </button>
    </nav>

    {activePage === 'conversion' ? (
      <ConversionPage />
    ) : (
      <div className="app-layout">
        {/* existing 3-panel layout — all existing JSX goes here unchanged */}
      </div>
    )}
  </div>
)
```

Note: wrap existing JSX in `<div className="app-layout">` and move inside the ternary. The `className="app"` on the outermost div should become `className="app-root"`.

- [ ] **Step 3: Add CSS to App.css**

Append to `frontend/src/App.css`:

```css
/* ============================================================
   Page Tab Navigation
   ============================================================ */
.app-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #1e1e2e;
}

.page-tab-bar {
  display: flex;
  background: #181825;
  border-bottom: 2px solid #313244;
  flex-shrink: 0;
}

.page-tab {
  padding: 10px 24px;
  background: transparent;
  border: none;
  color: #6c7086;
  font-size: 13px;
  cursor: pointer;
  transition: color 0.15s;
}

.page-tab:hover { color: #cdd6f4; }

.page-tab.active {
  color: #cdd6f4;
  font-weight: 600;
  border-top: 2px solid #89b4fa;
  margin-top: -2px;
  background: #1e1e2e;
}

/* ============================================================
   Conversion Page Layout
   ============================================================ */
.conversion-page {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.conversion-config-panel {
  width: 340px;
  background: #181825;
  border-right: 1px solid #313244;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.conversion-status-panel {
  flex: 1;
  background: #1e1e2e;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}

.conversion-section {
  padding: 12px 14px;
  border-bottom: 1px solid #313244;
}

.conversion-label {
  display: block;
  font-size: 10px;
  color: #89b4fa;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 8px;
}

.conversion-field { margin-bottom: 6px; }

.conversion-field-label {
  display: block;
  font-size: 10px;
  color: #a6adc8;
  margin-bottom: 3px;
}

.conversion-input {
  width: 100%;
  background: #313244;
  border: 1px solid #45475a;
  border-radius: 4px;
  color: #cdd6f4;
  font-size: 11px;
  padding: 4px 8px;
  box-sizing: border-box;
}

.conversion-input:focus {
  outline: none;
  border-color: #89b4fa;
}

.conversion-select {
  width: 100%;
  background: #313244;
  border: 1px solid #45475a;
  border-radius: 4px;
  color: #cdd6f4;
  font-size: 11px;
  padding: 4px 8px;
}

.conversion-profile-bar { background: #11111b; }

.conversion-profile-row {
  display: flex;
  gap: 6px;
  align-items: center;
}

.conversion-new-profile-row { margin-top: 6px; }

.conversion-row-2col {
  display: flex;
  gap: 8px;
  margin-bottom: 6px;
}

.conversion-kv-row {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 3px;
}

.conversion-key-input { width: 80px !important; }

.conversion-arrow { color: #6c7086; font-size: 10px; flex-shrink: 0; }

.conversion-tags { display: flex; flex-wrap: wrap; gap: 4px; }

.conversion-tag {
  background: #313244;
  color: #cdd6f4;
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.tag-remove {
  background: none;
  border: none;
  color: #f38ba8;
  cursor: pointer;
  padding: 0;
  font-size: 9px;
}

.conversion-tag-input-row { display: flex; gap: 4px; align-items: center; margin-top: 4px; }
.conversion-tag-input { width: 100px !important; }

.conversion-repo-list {
  display: flex;
  flex-direction: column;
  border: 1px solid #313244;
  border-radius: 6px;
  overflow: hidden;
}

.conversion-repo-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  cursor: pointer;
  border-bottom: 1px solid #313244;
}

.conversion-repo-item:last-child { border-bottom: none; }
.conversion-repo-item:hover { background: #313244; }
.conversion-repo-item.selected { background: #313244; }

.conversion-repo-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: #6c7086;
  flex-shrink: 0;
}

.conversion-repo-dot.mounted { background: #a6e3a1; }

.conversion-repo-name { font-size: 10px; color: #cdd6f4; }
.conversion-repo-mount { font-size: 9px; color: #6c7086; }
.conversion-repo-check { margin-left: auto; font-size: 10px; color: #89b4fa; }

.conversion-repo-create {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 10px;
  color: #89b4fa;
  border-top: 1px dashed #45475a;
}

.conversion-save-bar {
  padding: 10px 14px;
  border-top: 1px solid #313244;
  background: #11111b;
  margin-top: auto;
}

/* Watch card */
.conversion-watch-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #181825;
  padding: 12px 16px;
  border-radius: 6px;
  border: 1px solid #313244;
}

.conversion-watch-title { font-size: 12px; color: #cdd6f4; font-weight: 600; }
.conversion-watch-sub { font-size: 10px; color: #6c7086; margin-top: 2px; }

.conversion-watch-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toggle-btn {
  width: 36px; height: 20px;
  background: #45475a;
  border: none;
  border-radius: 10px;
  position: relative;
  cursor: pointer;
  transition: background 0.2s;
}

.toggle-btn.active { background: #a6e3a1; }

.toggle-knob {
  display: block;
  width: 16px; height: 16px;
  background: white;
  border-radius: 50%;
  position: absolute;
  top: 2px; left: 2px;
  transition: left 0.2s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}

.toggle-btn.active .toggle-knob { left: 18px; }

.toggle-label { font-size: 10px; color: #6c7086; }
.toggle-label.active { color: #a6e3a1; font-weight: 600; }

/* Controls */
.conversion-controls { display: flex; gap: 8px; }
.conversion-run-btn { flex: 1; }

/* Job list */
.conversion-jobs-section { display: flex; flex-direction: column; gap: 6px; }
.conversion-jobs-title {
  font-size: 10px;
  color: #a6adc8;
  text-transform: uppercase;
  letter-spacing: 1px;
}

.conversion-jobs-list {
  background: #181825;
  border: 1px solid #313244;
  border-radius: 6px;
  overflow: hidden;
}

.conversion-job-item {
  padding: 9px 12px;
  border-bottom: 1px solid #313244;
}

.conversion-job-item:last-child { border-bottom: none; }

.conversion-job-item.history {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.conversion-job-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 5px;
}

.conversion-job-folder { font-size: 11px; color: #cdd6f4; }

.conversion-job-badge {
  font-size: 9px;
  padding: 2px 8px;
  border-radius: 10px;
}

.conversion-job-badge.converting { color: #a6e3a1; background: #1e3a2e; }
.conversion-job-badge.queued { color: #89b4fa; background: #1a2a3e; }
.conversion-job-badge.done { color: #a6e3a1; }
.conversion-job-badge.failed { color: #f38ba8; }

.conversion-job-message { font-size: 9px; color: #6c7086; margin-top: 3px; }
.conversion-job-dest { font-size: 9px; color: #6c7086; margin-right: 8px; }
.conversion-job-outcome { display: flex; align-items: center; }

.conversion-progress-bar {
  height: 3px;
  background: #313244;
  border-radius: 2px;
  overflow: hidden;
}

.conversion-progress-fill.indeterminate {
  height: 100%;
  width: 40%;
  background: #a6e3a1;
  border-radius: 2px;
  animation: progress-slide 1.5s ease-in-out infinite;
}

@keyframes progress-slide {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(350%); }
}

.conversion-empty { font-size: 12px; color: #6c7086; text-align: center; padding: 24px; }

/* Button helpers */
.btn-sm {
  background: #313244;
  border: 1px solid #45475a;
  color: #cdd6f4;
  font-size: 10px;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}

.btn-xs {
  background: #313244;
  border: 1px solid #45475a;
  color: #cdd6f4;
  font-size: 9px;
  padding: 2px 7px;
  border-radius: 3px;
  cursor: pointer;
  flex-shrink: 0;
}

.btn-primary {
  width: 100%;
  background: #89b4fa;
  border: none;
  color: #1e1e2e;
  font-size: 11px;
  font-weight: 600;
  padding: 8px;
  border-radius: 4px;
  cursor: pointer;
}

.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-secondary {
  background: #313244;
  border: 1px solid #45475a;
  color: #cdd6f4;
  font-size: 11px;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
}

.btn-secondary:disabled { opacity: 0.4; cursor: not-allowed; }

.btn-danger { background: #f38ba8 !important; color: #1e1e2e !important; border-color: #f38ba8 !important; }
.btn-danger-outline {
  background: transparent;
  border: 1px solid #f38ba8;
  color: #f38ba8;
  font-size: 11px;
  font-weight: 600;
  padding: 6px 14px;
  border-radius: 4px;
  cursor: pointer;
}
```

- [ ] **Step 4: Verify TypeScript compiles clean**

```bash
cd /home/weed/psedulab/curation_tools/frontend
npx tsc --noEmit 2>&1 | head -30
```

Expected: no errors.

- [ ] **Step 5: Start dev servers and verify in browser**

```bash
cd /home/weed/psedulab/curation_tools
bash start.sh &
sleep 4
```

Open `http://localhost:5173` — verify:
1. "Conversion" tab is selected by default (left tab)
2. "Curation" tab switches to existing episode view
3. ConfigPanel shows profile selector, input path, HF repo list, config fields
4. StatusPanel shows watch toggle and "No jobs yet" message

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ConversionPage.tsx \
        frontend/src/App.tsx \
        frontend/src/App.css
git commit -m "feat: add ConversionPage and tab navigation to App"
```

---

## Task 9: Run Full Test Suite

- [ ] **Step 1: Run all tests**

```bash
cd /home/weed/psedulab/curation_tools
python -m pytest tests/ -v --ignore=tests/e2e 2>&1 | tail -20
```

Expected: all tests PASS. No failures.

- [ ] **Step 2: Final commit**

```bash
git add -A
git commit -m "feat: conversion pipeline page — watchdog + config profiles + SSE jobs"
```

---

## Out of Scope

- Persistent job history across server restarts
- Parallel multi-folder conversion
- Merge mode (`--merge` flag)
- Per-episode `metacard.json` editing from UI
