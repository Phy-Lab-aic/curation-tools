# Converter Control Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a web UI page to curation-tools that controls the rosbag-to-lerobot auto_converter Docker container (build/start/stop), streams real-time logs, and displays conversion progress.

**Architecture:** FastAPI backend wraps `docker compose` CLI via asyncio subprocess. A WebSocket endpoint streams container logs. React frontend adds a dedicated `/converter` page with controls, progress table, and log viewer. TopNav gets a status indicator dot.

**Tech Stack:** FastAPI (asyncio subprocess, WebSocket), React (TypeScript), Docker Compose CLI

---

## File Structure

**New backend files:**
- `backend/services/converter_service.py` — Docker CLI wrapper, log parsing, progress extraction
- `backend/routers/converter.py` — REST + WebSocket endpoints

**New frontend files:**
- `frontend/src/components/ConverterPage.tsx` — Page layout, state orchestration
- `frontend/src/components/ConverterControls.tsx` — Build/Start/Stop buttons + status badge
- `frontend/src/components/ConverterProgress.tsx` — Task-level conversion progress table
- `frontend/src/components/ConverterLogs.tsx` — WebSocket log viewer with auto-scroll

**Modified files:**
- `backend/main.py` — Register converter router
- `frontend/src/types/index.ts` — Converter types + AppState union member
- `frontend/src/hooks/useAppState.ts` — `navigateToConverter()` + converter view state
- `frontend/src/App.tsx` — Render ConverterPage
- `frontend/src/components/TopNav.tsx` — Status indicator dot
- `frontend/src/App.css` — Converter styles

---

### Task 1: Backend — converter_service.py

**Files:**
- Create: `backend/services/converter_service.py`

- [ ] **Step 1: Create converter_service.py with config and status**

```python
"""Docker CLI wrapper for rosbag-to-lerobot auto_converter."""

import asyncio
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Config — env var overrides
ROSBAG_PROJECT = Path(os.environ.get(
    "CONVERTER_PROJECT_PATH",
    "/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot",
))
COMPOSE_FILE = ROSBAG_PROJECT / "docker" / "docker-compose.yml"
PROJECT_NAME = "convert-server"
CONTAINER_NAME = "convert-server"


@dataclass
class TaskProgress:
    cell_task: str
    total: int
    done: int
    pending: int
    failed: int
    retry: int


@dataclass
class ConverterStatus:
    container_state: str  # "running" | "stopped" | "building" | "error" | "unknown"
    docker_available: bool
    tasks: list[TaskProgress] = field(default_factory=list)
    summary: str = ""


def _compose_cmd(*args: str) -> list[str]:
    return [
        "docker", "compose",
        "-p", PROJECT_NAME,
        "-f", str(COMPOSE_FILE),
        *args,
    ]


async def _run(cmd: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", "timeout"
    return proc.returncode, stdout.decode(), stderr.decode()


async def check_docker() -> bool:
    """Check if Docker daemon is reachable."""
    rc, _, _ = await _run(["docker", "info"], timeout=5.0)
    return rc == 0


async def get_container_state() -> str:
    """Get container state: running, exited, or stopped."""
    rc, stdout, _ = await _run([
        "docker", "inspect", CONTAINER_NAME,
        "--format", "{{.State.Status}}",
    ])
    if rc != 0:
        return "stopped"
    return stdout.strip()


# Module-level build state
_build_in_progress = False


async def get_status() -> ConverterStatus:
    """Get full converter status."""
    docker_ok = await check_docker()
    if not docker_ok:
        return ConverterStatus(
            container_state="unknown",
            docker_available=False,
        )

    if _build_in_progress:
        state = "building"
    else:
        raw = await get_container_state()
        state = "running" if raw == "running" else "stopped"

    status = ConverterStatus(container_state=state, docker_available=True)

    if state == "running":
        status.tasks, status.summary = await parse_progress()

    return status
```

- [ ] **Step 2: Add build, start, stop commands**

Append to `converter_service.py`:

```python
async def build_image(on_line: callable = None) -> int:
    """Build Docker image. Streams output lines via on_line callback.
    
    Returns exit code.
    """
    global _build_in_progress
    _build_in_progress = True
    try:
        cmd = _compose_cmd("build", "--no-cache", "convert-server")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for line in proc.stdout:
            text = line.decode(errors="replace").rstrip()
            if on_line:
                await on_line(text)
        await proc.wait()
        return proc.returncode
    finally:
        _build_in_progress = False


async def start_converter() -> tuple[bool, str]:
    """Start auto_converter container in detached mode.
    
    Returns (success, message).
    """
    current = await get_container_state()
    if current == "running":
        return False, "Container already running"

    # Clean up any stopped container with same name
    await _run(["docker", "rm", "-f", CONTAINER_NAME], timeout=10.0)

    cmd = _compose_cmd(
        "run", "-d", "--name", CONTAINER_NAME,
        "convert-server", "python3", "/app/auto_converter.py",
    )
    rc, stdout, stderr = await _run(cmd, timeout=30.0)
    if rc != 0:
        return False, f"Failed to start: {stderr}"
    return True, "Started"


async def stop_converter() -> tuple[bool, str]:
    """Stop converter via docker compose down.
    
    Returns (success, message).
    """
    cmd = _compose_cmd("down")
    rc, _, stderr = await _run(cmd, timeout=30.0)
    if rc != 0:
        return False, f"Failed to stop: {stderr}"
    return True, "Stopped"
```

- [ ] **Step 3: Add progress parsing from docker logs**

Append to `converter_service.py`:

```python
# Regex patterns for scan table parsing
_ROW_RE = re.compile(
    r"^\s+(.{1,36})\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$"
)
_TOTAL_RE = re.compile(
    r"Total:\s+(\d+)\s+tasks?\s*\|\s*(\d+)\s+recordings?\s*\|\s*"
    r"(\d+)\s+done\s*\|\s*(\d+)\s+pending\s*\|\s*(\d+)\s+failed"
)


async def parse_progress() -> tuple[list[TaskProgress], str]:
    """Parse the latest scan table from docker logs.
    
    Returns (task_list, summary_line).
    """
    rc, stdout, _ = await _run(
        ["docker", "logs", "--tail", "100", CONTAINER_NAME],
        timeout=10.0,
    )
    if rc != 0:
        return [], ""

    lines = stdout.splitlines()

    # Find the last scan table block (bounded by ━━ lines)
    block_start = -1
    block_end = -1
    for i in range(len(lines) - 1, -1, -1):
        if "━" in lines[i]:
            if block_end == -1:
                block_end = i
            else:
                block_start = i
                break

    if block_start == -1 or block_end == -1:
        return [], ""

    tasks = []
    summary = ""
    for line in lines[block_start:block_end + 1]:
        # Strip timestamp prefix if present (e.g., "2026-04-15 10:23:01 [INFO] ")
        content = line
        info_idx = content.find("[INFO]")
        if info_idx != -1:
            content = content[info_idx + 6:].strip()

        row_m = _ROW_RE.match(content)
        if row_m:
            tasks.append(TaskProgress(
                cell_task=row_m.group(1).strip(),
                total=int(row_m.group(2)),
                done=int(row_m.group(3)),
                pending=int(row_m.group(4)),
                failed=int(row_m.group(5)),
                retry=int(row_m.group(6)),
            ))

        total_m = _TOTAL_RE.search(content)
        if total_m:
            summary = content.strip()

    return tasks, summary


async def stream_logs(tail: int = 200):
    """Async generator that yields log lines from container.
    
    Yields str lines. Caller should handle cancellation.
    """
    cmd = ["docker", "logs", "-f", "--tail", str(tail), CONTAINER_NAME]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        async for line in proc.stdout:
            yield line.decode(errors="replace").rstrip()
    finally:
        proc.kill()
        await proc.wait()
```

- [ ] **Step 4: Commit**

```bash
git add backend/services/converter_service.py
git commit -m "feat(converter): add converter_service Docker CLI wrapper"
```

---

### Task 2: Backend — converter router

**Files:**
- Create: `backend/routers/converter.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Create converter router with REST endpoints**

```python
"""Converter control API — build/start/stop + status/progress."""

import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.services import converter_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/converter", tags=["converter"])


@router.get("/status")
async def get_status():
    """Get converter container status and progress summary."""
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
            }
            for t in status.tasks
        ],
        "summary": status.summary,
    }


@router.get("/progress")
async def get_progress():
    """Get conversion progress (parsed from latest scan table)."""
    tasks, summary = await converter_service.parse_progress()
    return {
        "tasks": [
            {
                "cell_task": t.cell_task,
                "total": t.total,
                "done": t.done,
                "pending": t.pending,
                "failed": t.failed,
                "retry": t.retry,
            }
            for t in tasks
        ],
        "summary": summary,
    }


@router.post("/build")
async def build():
    """Trigger Docker image build. Returns when build completes."""
    docker_ok = await converter_service.check_docker()
    if not docker_ok:
        raise HTTPException(503, "Docker daemon not available")

    lines: list[str] = []

    async def collect(line: str):
        lines.append(line)

    exit_code = await converter_service.build_image(on_line=collect)
    return {
        "success": exit_code == 0,
        "exit_code": exit_code,
        "output": "\n".join(lines[-50:]),  # last 50 lines
    }


@router.post("/start")
async def start():
    """Start auto_converter container."""
    docker_ok = await converter_service.check_docker()
    if not docker_ok:
        raise HTTPException(503, "Docker daemon not available")

    state = await converter_service.get_container_state()
    if state == "running":
        raise HTTPException(409, "Container already running")

    ok, msg = await converter_service.start_converter()
    if not ok:
        raise HTTPException(500, msg)
    return {"status": "started", "message": msg}


@router.post("/stop")
async def stop():
    """Stop converter container (idempotent)."""
    ok, msg = await converter_service.stop_converter()
    if not ok:
        raise HTTPException(500, msg)
    return {"status": "stopped", "message": msg}


@router.websocket("/logs")
async def logs_ws(ws: WebSocket):
    """Stream container logs via WebSocket."""
    await ws.accept()
    try:
        state = await converter_service.get_container_state()
        if state != "running":
            await ws.send_text("[converter not running]")
            await ws.close()
            return

        async for line in converter_service.stream_logs(tail=200):
            await ws.send_text(line)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Log WebSocket error: %s", e)
    finally:
        try:
            await ws.close()
        except Exception:
            pass
```

- [ ] **Step 2: Register router in main.py**

In `backend/main.py`, add import and include:

```python
# Add to imports (after existing router imports):
from backend.routers import converter

# Add after the last app.include_router() call:
app.include_router(converter.router)
```

- [ ] **Step 3: Commit**

```bash
git add backend/routers/converter.py backend/main.py
git commit -m "feat(converter): add converter REST + WebSocket router"
```

---

### Task 3: Frontend — Types and Navigation

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/hooks/useAppState.ts`

- [ ] **Step 1: Add converter types to types/index.ts**

Append at end of `frontend/src/types/index.ts`:

```typescript
// ── Converter types ────────────────────────────

export type ConverterState = 'running' | 'stopped' | 'building' | 'error' | 'unknown'

export interface ConverterTaskProgress {
  cell_task: string
  total: number
  done: number
  pending: number
  failed: number
  retry: number
}

export interface ConverterStatus {
  container_state: ConverterState
  docker_available: boolean
  tasks: ConverterTaskProgress[]
  summary: string
}
```

- [ ] **Step 2: Add converter view to AppState union**

In `frontend/src/types/index.ts`, change the `AppState` type:

```typescript
export type AppState =
  | { view: 'library' }
  | { view: 'cell'; cellName: string; cellPath: string }
  | { view: 'dataset'; cellName: string; cellPath: string; datasetPath: string; datasetName: string; tab: DatasetTab }
  | { view: 'converter' }
```

- [ ] **Step 3: Add navigateToConverter in useAppState.ts**

In `frontend/src/hooks/useAppState.ts`:

Add `navigateToConverter` to the interface and implementation:

```typescript
interface UseAppStateReturn {
  state: AppState
  navigateHome: () => void
  navigateToCell: (cellName: string, cellPath: string) => void
  navigateToDataset: (cellName: string, cellPath: string, datasetPath: string, datasetName: string) => void
  navigateToConverter: () => void
  setTab: (tab: DatasetTab) => void
}
```

Add inside the hook body:

```typescript
const navigateToConverter = useCallback(() => {
  setState({ view: 'converter' })
}, [])
```

Update return:

```typescript
return { state, navigateHome, navigateToCell, navigateToDataset, navigateToConverter, setTab }
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/hooks/useAppState.ts
git commit -m "feat(converter): add converter types and navigation state"
```

---

### Task 4: Frontend — ConverterControls component

**Files:**
- Create: `frontend/src/components/ConverterControls.tsx`

- [ ] **Step 1: Create ConverterControls.tsx**

```tsx
import { useState } from 'react'
import type { ConverterState } from '../types'

interface Props {
  containerState: ConverterState
  dockerAvailable: boolean
  onRefresh: () => void
}

const API = '/api/converter'

const STATE_LABEL: Record<ConverterState, string> = {
  running: 'Running',
  stopped: 'Stopped',
  building: 'Building',
  error: 'Error',
  unknown: 'Unknown',
}

const STATE_CLASS: Record<ConverterState, string> = {
  running: 'converter-status-running',
  stopped: 'converter-status-stopped',
  building: 'converter-status-building',
  error: 'converter-status-error',
  unknown: 'converter-status-stopped',
}

export function ConverterControls({ containerState, dockerAvailable, onRefresh }: Props) {
  const [loading, setLoading] = useState<string | null>(null)

  const act = async (action: 'build' | 'start' | 'stop') => {
    setLoading(action)
    try {
      const res = await fetch(`${API}/${action}`, { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        console.error(`${action} failed:`, body)
      }
      onRefresh()
    } finally {
      setLoading(null)
    }
  }

  const disabled = !dockerAvailable || loading !== null
  const isRunning = containerState === 'running'
  const isBuilding = containerState === 'building'

  return (
    <div className="converter-controls">
      <div className="converter-controls-buttons">
        <button
          className="btn-secondary"
          disabled={disabled || isRunning || isBuilding}
          onClick={() => act('build')}
        >
          {loading === 'build' ? 'Building...' : 'Build'}
        </button>
        <button
          className="btn-primary"
          disabled={disabled || isRunning || isBuilding}
          onClick={() => act('start')}
        >
          {loading === 'start' ? 'Starting...' : 'Start'}
        </button>
        <button
          className="btn-secondary converter-stop-btn"
          disabled={disabled || (!isRunning && !isBuilding)}
          onClick={() => act('stop')}
        >
          {loading === 'stop' ? 'Stopping...' : 'Stop'}
        </button>
      </div>
      <div className={`converter-status-badge ${STATE_CLASS[containerState]}`}>
        <span className="converter-status-dot" />
        {STATE_LABEL[containerState]}
      </div>
      {!dockerAvailable && (
        <span className="converter-docker-warn">Docker not available</span>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ConverterControls.tsx
git commit -m "feat(converter): add ConverterControls component"
```

---

### Task 5: Frontend — ConverterProgress component

**Files:**
- Create: `frontend/src/components/ConverterProgress.tsx`

- [ ] **Step 1: Create ConverterProgress.tsx**

```tsx
import type { ConverterTaskProgress } from '../types'

interface Props {
  tasks: ConverterTaskProgress[]
  summary: string
}

export function ConverterProgress({ tasks, summary }: Props) {
  if (tasks.length === 0) {
    return (
      <div className="converter-progress-empty">
        No conversion data available
      </div>
    )
  }

  const totals = tasks.reduce(
    (acc, t) => ({
      total: acc.total + t.total,
      done: acc.done + t.done,
      pending: acc.pending + t.pending,
      failed: acc.failed + t.failed,
    }),
    { total: 0, done: 0, pending: 0, failed: 0 },
  )

  return (
    <div className="converter-progress">
      <table className="converter-progress-table">
        <thead>
          <tr>
            <th>Cell/Task</th>
            <th>Total</th>
            <th>Done</th>
            <th>Pending</th>
            <th>Failed</th>
            <th>Progress</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map(t => {
            const pct = t.total > 0 ? Math.round((t.done / t.total) * 100) : 0
            return (
              <tr key={t.cell_task}>
                <td className="mono">{t.cell_task}</td>
                <td>{t.total}</td>
                <td className="text-green">{t.done}</td>
                <td className="text-yellow">{t.pending}</td>
                <td className={t.failed > 0 ? 'text-red' : ''}>{t.failed}</td>
                <td>
                  <div className="converter-bar">
                    <div className="converter-bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
        <tfoot>
          <tr>
            <td><strong>Total</strong></td>
            <td><strong>{totals.total}</strong></td>
            <td className="text-green"><strong>{totals.done}</strong></td>
            <td className="text-yellow"><strong>{totals.pending}</strong></td>
            <td className={totals.failed > 0 ? 'text-red' : ''}><strong>{totals.failed}</strong></td>
            <td>
              <div className="converter-bar">
                <div
                  className="converter-bar-fill"
                  style={{ width: `${totals.total > 0 ? Math.round((totals.done / totals.total) * 100) : 0}%` }}
                />
              </div>
            </td>
          </tr>
        </tfoot>
      </table>
      {summary && <div className="converter-summary">{summary}</div>}
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ConverterProgress.tsx
git commit -m "feat(converter): add ConverterProgress table component"
```

---

### Task 6: Frontend — ConverterLogs component

**Files:**
- Create: `frontend/src/components/ConverterLogs.tsx`

- [ ] **Step 1: Create ConverterLogs.tsx**

```tsx
import { useEffect, useRef, useState } from 'react'

interface Props {
  containerState: string
}

const MAX_LINES = 500

export function ConverterLogs({ containerState }: Props) {
  const [lines, setLines] = useState<string[]>([])
  const [autoScroll, setAutoScroll] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (containerState !== 'running') return

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${window.location.host}/api/converter/logs`)

    ws.onmessage = (evt) => {
      setLines(prev => {
        const next = [...prev, evt.data]
        return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next
      })
    }

    ws.onclose = () => {
      setLines(prev => [...prev, '[connection closed]'])
    }

    return () => {
      ws.close()
    }
  }, [containerState])

  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [lines, autoScroll])

  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setAutoScroll(atBottom)
  }

  return (
    <div className="converter-logs-wrapper">
      <div className="converter-logs-header">
        <span>Logs</span>
        {!autoScroll && (
          <button
            className="converter-scroll-btn"
            onClick={() => {
              setAutoScroll(true)
              bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
            }}
          >
            Scroll to bottom
          </button>
        )}
      </div>
      <div
        className="converter-logs"
        ref={containerRef}
        onScroll={handleScroll}
      >
        {lines.length === 0 ? (
          <div className="converter-logs-empty">
            {containerState === 'running' ? 'Connecting...' : 'Start converter to see logs'}
          </div>
        ) : (
          lines.map((line, i) => (
            <div key={i} className="converter-log-line">
              {line}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/ConverterLogs.tsx
git commit -m "feat(converter): add ConverterLogs WebSocket viewer"
```

---

### Task 7: Frontend — ConverterPage + App integration

**Files:**
- Create: `frontend/src/components/ConverterPage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Create ConverterPage.tsx**

```tsx
import { useCallback, useEffect, useState } from 'react'
import { ConverterControls } from './ConverterControls'
import { ConverterProgress } from './ConverterProgress'
import { ConverterLogs } from './ConverterLogs'
import type { ConverterStatus, ConverterState } from '../types'

const API = '/api/converter'

export function ConverterPage() {
  const [status, setStatus] = useState<ConverterStatus>({
    container_state: 'unknown',
    docker_available: false,
    tasks: [],
    summary: '',
  })

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/status`)
      if (res.ok) {
        setStatus(await res.json())
      }
    } catch {
      // ignore fetch errors
    }
  }, [])

  // Poll status every 5 seconds
  useEffect(() => {
    fetchStatus()
    const id = setInterval(fetchStatus, 5000)
    return () => clearInterval(id)
  }, [fetchStatus])

  // Poll progress every 10 seconds when running
  useEffect(() => {
    if (status.container_state !== 'running') return

    const id = setInterval(async () => {
      try {
        const res = await fetch(`${API}/progress`)
        if (res.ok) {
          const data = await res.json()
          setStatus(prev => ({ ...prev, tasks: data.tasks, summary: data.summary }))
        }
      } catch {
        // ignore
      }
    }, 10000)

    return () => clearInterval(id)
  }, [status.container_state])

  return (
    <div className="converter-page">
      <ConverterControls
        containerState={status.container_state}
        dockerAvailable={status.docker_available}
        onRefresh={fetchStatus}
      />
      <ConverterProgress tasks={status.tasks} summary={status.summary} />
      <ConverterLogs containerState={status.container_state} />
    </div>
  )
}
```

- [ ] **Step 2: Add converter view to App.tsx**

In `frontend/src/App.tsx`:

Add import:

```typescript
import { ConverterPage } from './components/ConverterPage'
```

Add inside the `<div className="page-content">` block, after the dataset view:

```tsx
{state.view === 'converter' && (
  <ConverterPage />
)}
```

Update the `useAppState` destructuring to include `navigateToConverter`:

```typescript
const { state, navigateHome, navigateToCell, navigateToDataset, navigateToConverter, setTab } = useAppState()
```

Pass `navigateToConverter` to TopNav:

```tsx
<TopNav
  state={state}
  onNavigateHome={navigateHome}
  onNavigateCell={navigateToCell}
  onTabChange={setTab}
  onNavigateConverter={navigateToConverter}
/>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ConverterPage.tsx frontend/src/App.tsx
git commit -m "feat(converter): add ConverterPage and wire into App"
```

---

### Task 8: Frontend — TopNav status indicator

**Files:**
- Modify: `frontend/src/components/TopNav.tsx`

- [ ] **Step 1: Add status indicator to TopNav**

Replace the full `TopNav.tsx` content:

```tsx
import { useEffect, useState } from 'react'
import type { AppState, DatasetTab, ConverterState } from '../types'

interface TopNavProps {
  state: AppState
  onNavigateHome: () => void
  onNavigateCell: (cellName: string, cellPath: string) => void
  onTabChange?: (tab: DatasetTab) => void
  onNavigateConverter?: () => void
}

const TABS: { id: DatasetTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'curate',   label: 'Curate' },
  { id: 'fields',   label: 'Fields' },
]

const DOT_CLASS: Record<ConverterState, string> = {
  running: 'converter-dot-running',
  stopped: 'converter-dot-stopped',
  building: 'converter-dot-building',
  error: 'converter-dot-error',
  unknown: 'converter-dot-stopped',
}

export function TopNav({ state, onNavigateHome, onNavigateCell, onTabChange, onNavigateConverter }: TopNavProps) {
  const [converterState, setConverterState] = useState<ConverterState>('unknown')

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch('/api/converter/status')
        if (res.ok) {
          const data = await res.json()
          setConverterState(data.container_state)
        }
      } catch {
        setConverterState('unknown')
      }
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [])

  return (
    <nav className="top-nav">
      <button className="top-nav-logo" onClick={onNavigateHome}>
        robo<span>data</span>
      </button>

      <button
        className={`converter-indicator ${DOT_CLASS[converterState]}`}
        onClick={onNavigateConverter}
        title={`Converter: ${converterState}`}
      >
        <span className="converter-nav-dot" />
      </button>

      <div className="top-nav-breadcrumb">
        {(state.view === 'cell' || state.view === 'dataset') && (
          <>
            <span className="sep">/</span>
            <button onClick={() => onNavigateCell(state.cellName, state.cellPath)}>
              <em>{state.cellName}</em>
            </button>
          </>
        )}
        {state.view === 'dataset' && (
          <>
            <span className="sep">/</span>
            <em>{state.datasetName}</em>
          </>
        )}
        {state.view === 'converter' && (
          <>
            <span className="sep">/</span>
            <em>Converter</em>
          </>
        )}
      </div>

      {state.view === 'dataset' && (
        <div className="top-nav-tabs">
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`top-nav-tab${state.tab === tab.id ? ' active' : ''}`}
              onClick={() => onTabChange?.(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}
    </nav>
  )
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/TopNav.tsx
git commit -m "feat(converter): add status indicator to TopNav"
```

---

### Task 9: Frontend — CSS styles

**Files:**
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Append converter styles to App.css**

Add at the end of `frontend/src/App.css`:

```css
/* ── Converter page ──────────────────────────── */
.converter-page {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 16px;
  gap: 12px;
}

/* Controls bar */
.converter-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  flex-shrink: 0;
}
.converter-controls-buttons {
  display: flex;
  gap: 6px;
}
.converter-stop-btn:not(:disabled) {
  color: var(--c-red);
  border-color: var(--c-red);
}
.converter-status-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  margin-left: auto;
}
.converter-status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.converter-status-running .converter-status-dot { background: var(--c-green); }
.converter-status-stopped .converter-status-dot { background: var(--text-dim); }
.converter-status-building .converter-status-dot { background: var(--c-yellow); animation: pulse 1.5s ease-in-out infinite; }
.converter-status-error .converter-status-dot { background: var(--c-red); }
.converter-docker-warn {
  font-size: 11px;
  color: var(--c-red);
}

/* Progress table */
.converter-progress {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  flex-shrink: 0;
}
.converter-progress-empty {
  padding: 20px;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}
.converter-progress-table {
  width: 100%;
  border-collapse: collapse;
}
.converter-progress-table th {
  text-align: left;
  font-size: 10px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}
.converter-progress-table td {
  font-size: 12px;
  color: var(--text);
  padding: 6px 12px;
  border-bottom: 1px solid #1a1a1a;
  font-variant-numeric: tabular-nums;
}
.converter-progress-table tfoot td {
  border-top: 1px solid var(--border);
  border-bottom: none;
}
.converter-bar {
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  width: 80px;
}
.converter-bar-fill {
  height: 4px;
  background: var(--c-green);
  border-radius: 2px;
  transition: width 0.3s;
}
.converter-summary {
  padding: 6px 12px;
  font-size: 11px;
  color: var(--text-muted);
  border-top: 1px solid var(--border);
}

/* Log viewer */
.converter-logs-wrapper {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  min-height: 0;
}
.converter-logs-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  font-size: 11px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.converter-scroll-btn {
  background: none;
  border: 1px solid var(--border2);
  border-radius: 3px;
  padding: 2px 8px;
  font-size: 10px;
  color: var(--text-muted);
  cursor: pointer;
  text-transform: none;
  letter-spacing: normal;
}
.converter-scroll-btn:hover { color: var(--text); border-color: var(--border); }
.converter-logs {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 11px;
  line-height: 1.6;
}
.converter-logs-empty {
  color: var(--text-dim);
  padding: 20px;
  text-align: center;
}
.converter-log-line {
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text-muted);
}

/* TopNav converter indicator */
.converter-indicator {
  background: none;
  border: none;
  display: flex;
  align-items: center;
  padding: 0 8px;
  cursor: pointer;
}
.converter-indicator:hover .converter-nav-dot { transform: scale(1.3); }
.converter-nav-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  transition: background 0.2s, transform 0.15s;
}
.converter-dot-running .converter-nav-dot { background: var(--c-green); }
.converter-dot-stopped .converter-nav-dot { background: var(--text-dim); }
.converter-dot-building .converter-nav-dot { background: var(--c-yellow); animation: pulse 1.5s ease-in-out infinite; }
.converter-dot-error .converter-nav-dot { background: var(--c-red); }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/App.css
git commit -m "feat(converter): add converter page CSS styles"
```

---

### Task 10: Integration test — manual verification

- [ ] **Step 1: Start the dev servers**

```bash
cd /home/tommoro/jm_ws/local_data_pipline/curation-tools
# Backend
cd backend && python -m backend.main &
# Frontend  
cd frontend && npm run dev &
```

- [ ] **Step 2: Verify status endpoint**

```bash
curl http://localhost:8001/api/converter/status
```

Expected: `{"container_state": "stopped", "docker_available": true, "tasks": [], "summary": ""}`

- [ ] **Step 3: Verify UI renders**

Open `http://localhost:5173` in browser:
1. TopNav should show a grey dot next to the logo
2. Click the dot — should navigate to converter page
3. Should see controls (Build/Start/Stop), empty progress table, and log area
4. Click "Build" — should trigger Docker build (may take a while)
5. Click "Start" — converter should start, logs should stream, progress table should populate
6. Click "Stop" — converter should stop gracefully

- [ ] **Step 4: Final commit with all files**

```bash
git add -A
git status  # verify only expected files
git commit -m "feat: converter control panel — build/start/stop with logs and progress"
```
