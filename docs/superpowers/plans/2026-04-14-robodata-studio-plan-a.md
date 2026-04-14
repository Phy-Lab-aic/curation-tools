# robodata-studio — Plan A: Foundation + Navigation + Curate Redesign

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove conversion/HubSync code, introduce 3-level navigation (Library → Cell → Dataset), apply Grafana-style black palette, and restyle the existing Curate tab.

**Architecture:** React state machine in App.tsx drives Library/Cell/Dataset views without React Router. A new FastAPI `/api/cells` endpoint scans `allowed_dataset_roots` for `cell*` subdirectories. CSS custom properties replace all hardcoded Catppuccin colors.

**Tech Stack:** FastAPI, pyarrow, React 18, TypeScript, Vite, axios

---

## Background: Domain Concepts

- **Cell:** A physical robot station (e.g. `cell001`). Detected by scanning `allowed_dataset_roots` for subdirectories matching `cell*`.
- **Dataset:** A LeRobot v3.0 dataset inside a cell. Identified by having `meta/info.json`.
- **Sidecar JSON:** Grade/tag annotations are stored in `~/.local/share/curation-tools/annotations/<name>_<hash>.json` (not in the dataset dir) so read-only mounts work.

---

## File Map

**Deleted:**
- `backend/routers/conversion.py`
- `backend/services/conversion_service.py`
- `backend/routers/hf_sync.py`
- `backend/services/hf_sync_service.py`
- `frontend/src/components/ConversionPage.tsx`
- `frontend/src/components/conversion/ConfigPanel.tsx`
- `frontend/src/components/conversion/StatusPanel.tsx`
- `frontend/src/hooks/useConversion.ts`
- `frontend/src/components/HubSync.tsx`

**Created:**
- `backend/routers/cells.py`
- `backend/services/cell_service.py`
- `tests/test_cell_service.py`
- `frontend/src/components/TopNav.tsx`
- `frontend/src/components/LibraryPage.tsx`
- `frontend/src/components/CellPage.tsx`
- `frontend/src/components/DatasetPage.tsx`
- `frontend/src/hooks/useCells.ts`

**Modified:**
- `backend/main.py` — remove old routers, add cells router
- `backend/config.py` — add `cell_name_pattern`
- `backend/models/schemas.py` — add CellInfo, DatasetSummary
- `frontend/src/App.css` — CSS variable system, remove Catppuccin
- `frontend/src/App.tsx` — 3-level state machine
- `frontend/src/types/index.ts` — add Cell, DatasetSummary types
- `frontend/src/components/EpisodeList.tsx` — grade dot, black palette
- `frontend/src/components/EpisodeEditor.tsx` — D1 grade UI, remove GRADE_COLORS

---

## Task 1: Delete Dead Code

**Files:**
- Delete: `backend/routers/conversion.py`
- Delete: `backend/services/conversion_service.py`
- Delete: `backend/routers/hf_sync.py`
- Delete: `backend/services/hf_sync_service.py`
- Delete: `frontend/src/components/ConversionPage.tsx`
- Delete: `frontend/src/components/conversion/ConfigPanel.tsx`
- Delete: `frontend/src/components/conversion/StatusPanel.tsx`
- Delete: `frontend/src/hooks/useConversion.ts`
- Delete: `frontend/src/components/HubSync.tsx`
- Modify: `backend/main.py`

- [ ] **Step 1: Delete backend files**

```bash
rm backend/routers/conversion.py
rm backend/services/conversion_service.py
rm backend/routers/hf_sync.py
rm backend/services/hf_sync_service.py
```

- [ ] **Step 2: Delete frontend files**

```bash
rm frontend/src/components/ConversionPage.tsx
rm -rf frontend/src/components/conversion/
rm frontend/src/hooks/useConversion.ts
rm frontend/src/components/HubSync.tsx
```

- [ ] **Step 3: Remove deleted imports from `backend/main.py`**

Replace the imports and router registrations. The new `main.py`:

```python
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.routers import datasets, episodes, tasks, rerun, videos, scalars, dataset_ops
from backend.services import rerun_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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


app = FastAPI(
    title="robodata-studio",
    description="Internal curation and analytics tool for LeRobot datasets",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(datasets.router)
app.include_router(episodes.router)
app.include_router(tasks.router)
app.include_router(rerun.router)
app.include_router(videos.router)
app.include_router(scalars.router)
app.include_router(dataset_ops.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


def start():
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.fastapi_port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    start()
```

- [ ] **Step 4: Verify backend starts without errors**

```bash
uv run python -m backend.main
```

Expected: server starts on port 8000, no ImportError.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove conversion and hf_sync modules"
```

---

## Task 2: CSS Variable System

**Files:**
- Modify: `frontend/src/App.css`
- Modify: `frontend/src/types/index.ts`

- [ ] **Step 1: Rewrite `frontend/src/App.css` with CSS variables**

Replace the entire file content:

```css
/* ── Design tokens ─────────────────────────────── */
:root {
  --bg:          #0f0f0f;
  --panel:       #161616;
  --panel2:      #1c1c1c;
  --border:      #222222;
  --border2:     #2a2a2a;
  --text:        #d9d9d9;
  --text-muted:  #555555;
  --text-dim:    #333333;
  --accent:      #ff9830;
  --accent-dim:  rgba(255, 152, 48, 0.08);
  /* Data colours — only for chart series and grade state */
  --c-green:  #73bf69;
  --c-yellow: #fade2a;
  --c-red:    #f08080;
  --c-blue:   #5794f2;
  --c-purple: #b877d9;
}

/* ── Reset ─────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; }

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
  font-size: 13px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

button { cursor: pointer; font-family: inherit; }
input, select, textarea { font-family: inherit; }
code, .mono { font-family: 'JetBrains Mono', 'Fira Code', monospace; }

/* ── Scrollbar ─────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border2); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #3a3a3a; }

/* ── App shell ─────────────────────────────────── */
.app-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  background: var(--bg);
}

/* ── TopNav ────────────────────────────────────── */
.top-nav {
  height: 40px;
  background: #111111;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: stretch;
  flex-shrink: 0;
  padding: 0 16px;
  gap: 0;
}

.top-nav-logo {
  font-size: 13px;
  font-weight: 800;
  color: var(--text);
  letter-spacing: -0.04em;
  display: flex;
  align-items: center;
  margin-right: 20px;
  text-decoration: none;
}
.top-nav-logo span { color: var(--accent); }

.top-nav-breadcrumb {
  display: flex;
  align-items: center;
  font-size: 11px;
  color: var(--text-muted);
  gap: 6px;
  flex: 1;
}
.top-nav-breadcrumb em { color: #888888; font-style: normal; }
.top-nav-breadcrumb .sep { color: var(--text-dim); }
.top-nav-breadcrumb button {
  background: none;
  border: none;
  color: #888888;
  font-size: 11px;
  padding: 0;
  cursor: pointer;
}
.top-nav-breadcrumb button:hover { color: var(--text); }

.top-nav-tabs {
  display: flex;
}
.top-nav-tab {
  padding: 0 14px;
  font-size: 11px;
  color: var(--text-muted);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  height: 100%;
}
.top-nav-tab:hover { color: var(--text); }
.top-nav-tab.active {
  color: var(--text);
  border-bottom-color: var(--accent);
}

/* ── Page container ────────────────────────────── */
.page-content {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Library page ──────────────────────────────── */
.library-page {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.library-filter-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
}

.library-search {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text);
  outline: none;
  width: 220px;
}
.library-search:focus { border-color: var(--accent); }
.library-search::placeholder { color: var(--text-muted); }

.filter-chip {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 3px 12px;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
}
.filter-chip:hover { border-color: var(--border2); color: var(--text); }
.filter-chip.active {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-dim);
}

.library-section-header {
  font-size: 10px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 4px 0;
  margin: 16px 0 8px;
  border-bottom: 1px solid var(--border);
}

.cell-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
  margin-bottom: 24px;
}

.cell-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.cell-card:hover { border-color: #3a3a3a; }

.cell-card-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 7px;
}

.cell-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.cell-status-dot.active { background: var(--c-green); }
.cell-status-dot.idle { background: var(--text-dim); }

.cell-card-meta { font-size: 11px; color: var(--text-muted); }

/* ── Cell page ─────────────────────────────────── */
.cell-page {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.dataset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
}

.dataset-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color 0.15s;
}
.dataset-card:hover { border-color: #3a3a3a; }
.dataset-card.loaded { border-color: rgba(255,152,48,0.3); }

.dataset-card-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.dataset-card-meta {
  font-size: 10px;
  color: var(--text-muted);
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.dataset-card-progress {
  background: var(--border);
  border-radius: 2px;
  height: 3px;
  margin-bottom: 5px;
}
.dataset-card-progress-fill {
  height: 3px;
  border-radius: 2px;
  transition: width 0.3s;
}

.dataset-card-grade-bar {
  display: flex;
  gap: 2px;
  height: 3px;
  border-radius: 2px;
  overflow: hidden;
}
.grade-seg { height: 3px; border-radius: 1px; }

/* ── Dataset page (tabs) ───────────────────────── */
.dataset-page {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

/* ── Curate tab layout ─────────────────────────── */
.curate-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
}

/* Episode list sidebar */
.episode-sidebar {
  width: 200px;
  flex-shrink: 0;
  background: #111;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}

.episode-sidebar-header {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.episode-sidebar-title {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.episode-progress-count {
  font-size: 10px;
  color: var(--accent);
  font-variant-numeric: tabular-nums;
}

.episode-list {
  flex: 1;
  overflow-y: auto;
}

.episode-item {
  padding: 6px 10px;
  display: flex;
  align-items: center;
  gap: 7px;
  border-bottom: 1px solid #1a1a1a;
  cursor: pointer;
  border-left: 2px solid transparent;
}
.episode-item:hover { background: var(--panel2); }
.episode-item.active {
  background: var(--accent-dim);
  border-left-color: var(--accent);
}

.episode-grade-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.episode-grade-dot.good   { background: var(--c-green); }
.episode-grade-dot.normal { background: var(--c-yellow); }
.episode-grade-dot.bad    { background: var(--c-red); }
.episode-grade-dot.none   { background: var(--text-dim); }

.episode-item-idx {
  font-size: 10px;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  font-family: monospace;
  width: 44px;
  flex-shrink: 0;
}
.episode-item.active .episode-item-idx { color: var(--accent); }

.episode-item-len {
  font-size: 9px;
  color: var(--text-dim);
  margin-left: auto;
  font-family: monospace;
}

/* Center panel */
.curate-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  min-width: 0;
}

/* Grade bar (D1 — underline tab style) */
.grade-bar {
  background: #111;
  border-top: 1px solid var(--border);
  padding: 8px 16px;
  display: flex;
  align-items: center;
  gap: 0;
}

.grade-btn {
  padding: 6px 20px;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-dim);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  letter-spacing: 0.02em;
  transition: color 0.1s, border-color 0.1s;
}
.grade-btn:hover { color: var(--text-muted); }
.grade-btn.active {
  color: var(--text);
  border-bottom-color: var(--text);
}

.grade-kbd-hint {
  margin-left: auto;
  display: flex;
  gap: 3px;
  align-items: center;
}
.grade-kbd-hint kbd {
  background: var(--panel2);
  border: 1px solid var(--border2);
  border-radius: 2px;
  padding: 1px 5px;
  font-size: 9px;
  color: var(--text-muted);
  font-family: monospace;
}

/* Right panel */
.curate-right {
  width: 220px;
  flex-shrink: 0;
  background: #111;
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}

.right-tabs {
  display: flex;
  border-bottom: 1px solid var(--border);
}
.right-tab {
  flex: 1;
  text-align: center;
  padding: 7px 0;
  font-size: 10px;
  color: var(--text-muted);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
}
.right-tab.active {
  color: var(--text);
  border-bottom-color: var(--accent);
}

/* Episode details */
.ep-details {
  padding: 12px;
  border-bottom: 1px solid var(--border);
}
.ep-details-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
}
.ep-details-key { font-size: 10px; color: var(--text-muted); }
.ep-details-val { font-size: 10px; color: var(--text); font-family: monospace; }

/* Tag chips */
.tag-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
}
.tag-chip {
  background: var(--panel2);
  border: 1px solid var(--border2);
  border-radius: 3px;
  padding: 2px 6px;
  font-size: 9px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 3px;
}
.tag-chip-remove {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 9px;
  padding: 0;
  line-height: 1;
}
.tag-chip-remove:hover { color: var(--text-muted); }
.tag-add-chip {
  background: none;
  border: 1px dashed var(--border2);
  border-radius: 3px;
  padding: 2px 8px;
  font-size: 9px;
  color: var(--text-dim);
  cursor: pointer;
}
.tag-add-chip:hover { color: var(--text-muted); border-color: var(--border); }

/* Terminal frames */
.terminal-bar {
  background: var(--panel);
  border-top: 1px solid var(--border);
  padding: 5px 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.terminal-bar-label { font-size: 9px; color: var(--text-dim); }
.terminal-frame-chip {
  background: var(--panel2);
  border: 1px solid var(--border2);
  border-radius: 3px;
  padding: 2px 7px;
  font-size: 9px;
  color: var(--text-muted);
  font-family: monospace;
  cursor: pointer;
}
.terminal-frame-chip.active { border-color: var(--accent); color: var(--accent); }

/* ── Shared form elements ──────────────────────── */
.form-input {
  background: var(--panel2);
  border: 1px solid var(--border2);
  border-radius: 4px;
  padding: 5px 9px;
  font-size: 12px;
  color: var(--text);
  outline: none;
  width: 100%;
}
.form-input:focus { border-color: var(--accent); }
.form-input::placeholder { color: var(--text-muted); }

.btn-primary {
  background: var(--accent);
  border: none;
  border-radius: 5px;
  padding: 6px 14px;
  font-size: 11px;
  font-weight: 700;
  color: #000;
  cursor: pointer;
}
.btn-primary:hover { opacity: 0.9; }
.btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }

.btn-secondary {
  background: none;
  border: 1px solid var(--border2);
  border-radius: 5px;
  padding: 6px 12px;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
}
.btn-secondary:hover { border-color: var(--border); color: var(--text); }

/* ── Scrubber / progress ───────────────────────── */
.scrubber {
  height: 2px;
  background: var(--border2);
  position: relative;
  flex-shrink: 0;
  margin: 0 12px;
}
.scrubber-fill {
  height: 2px;
  background: var(--accent);
  border-radius: 1px;
}

/* ── Stats bar ─────────────────────────────────── */
.stats-bar {
  display: flex;
  gap: 10px;
  padding: 14px;
  flex-shrink: 0;
}
.stat-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 14px;
  flex: 1;
}
.stat-card-n {
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  line-height: 1;
  margin-bottom: 3px;
  font-variant-numeric: tabular-nums;
}
.stat-card-l { font-size: 10px; color: var(--text-muted); }

/* ── Utility ───────────────────────────────────── */
.text-muted { color: var(--text-muted); }
.text-accent { color: var(--accent); }
.text-green  { color: var(--c-green); }
.text-yellow { color: var(--c-yellow); }
.text-red    { color: var(--c-red); }
```

- [ ] **Step 2: Update `frontend/src/types/index.ts`** — remove GRADE_COLORS, add new types

```typescript
export const GRADES = ['good', 'normal', 'bad'] as const
export type Grade = (typeof GRADES)[number]

// Removed: GRADE_COLORS (replaced by CSS variables --c-green/--c-yellow/--c-red)

export interface DatasetInfo {
  path: string
  name: string
  fps: number
  total_episodes: number
  total_tasks: number
  robot_type: string | null
  features: Record<string, unknown>
}

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
}

export interface Task {
  task_index: number
  task_instruction: string
}

export interface EpisodeUpdate {
  grade: string | null
  tags: string[]
}

export interface TaskUpdate {
  task_instruction: string
}

// ── New types for 3-level navigation ──────────────

export interface CellInfo {
  name: string        // "cell001"
  path: string        // "/tmp/hf-mounts/Phy-lab/dataset/cell001"
  mount_root: string  // "/tmp/hf-mounts/Phy-lab/dataset"
  dataset_count: number
  active: boolean     // mount path is accessible
}

export interface DatasetSummary {
  name: string
  path: string
  total_episodes: number
  graded_count: number
  robot_type: string | null
  fps: number
}

export type DatasetTab = 'overview' | 'curate' | 'fields' | 'ops'

export type AppState =
  | { view: 'library' }
  | { view: 'cell'; cellName: string; cellPath: string }
  | { view: 'dataset'; cellName: string; cellPath: string; datasetPath: string; datasetName: string; tab: DatasetTab }
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -40
```

Expected: errors only from files still using `GRADE_COLORS` — we'll fix those in later tasks.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.css frontend/src/types/index.ts
git commit -m "refactor: CSS variable system and updated types"
```

---

## Task 3: Backend — Cell Service + Router

**Files:**
- Create: `backend/services/cell_service.py`
- Create: `backend/routers/cells.py`
- Create: `tests/test_cell_service.py`
- Modify: `backend/config.py`
- Modify: `backend/models/schemas.py`

- [ ] **Step 1: Add `cell_name_pattern` to `backend/config.py`**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    dataset_path: str = "/data/datasets"
    allowed_dataset_roots: list[str] = [
        "/tmp/hf-mounts/Phy-lab/dataset",
        "/data/datasets",
    ]
    host: str = "127.0.0.1"
    fastapi_port: int = 8000
    rerun_grpc_port: int = 9876
    rerun_web_port: int = 9090
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    annotations_path: str = ""
    enable_rerun: bool = False
    debug: bool = False
    cell_name_pattern: str = "cell*"

    model_config = {"env_prefix": "CURATION_"}


settings = Settings()
```

- [ ] **Step 2: Add schemas to `backend/models/schemas.py`**

Append at the end of the file:

```python
class CellInfo(BaseModel):
    name: str
    path: str
    mount_root: str
    dataset_count: int
    active: bool


class DatasetSummary(BaseModel):
    name: str
    path: str
    total_episodes: int
    graded_count: int
    robot_type: str | None = None
    fps: int
```

- [ ] **Step 3: Write the failing tests in `tests/test_cell_service.py`**

```python
import json
from pathlib import Path

import pytest

from backend.services.cell_service import scan_cells, get_datasets_in_cell


@pytest.fixture
def mock_mount(tmp_path: Path):
    """Create a fake mount structure:
    tmp_path/
      cell001/
        dataset_a/meta/info.json
        dataset_b/meta/info.json
      cell002/
        dataset_c/meta/info.json
      not_a_cell/          ← no cell* prefix, should be ignored
        dataset_d/meta/info.json
    """
    for cell, datasets in [
        ("cell001", ["dataset_a", "dataset_b"]),
        ("cell002", ["dataset_c"]),
    ]:
        for ds in datasets:
            info = {
                "fps": 30,
                "total_episodes": 10,
                "robot_type": "ur5e",
                "features": {},
                "total_tasks": 2,
            }
            p = tmp_path / cell / ds / "meta"
            p.mkdir(parents=True)
            (p / "info.json").write_text(json.dumps(info))

    # Not a cell — should be ignored
    other = tmp_path / "not_a_cell" / "dataset_d" / "meta"
    other.mkdir(parents=True)
    (other / "info.json").write_text("{}")

    return tmp_path


def test_scan_cells_finds_cell_dirs(mock_mount):
    cells = scan_cells([str(mock_mount)], pattern="cell*")
    names = {c.name for c in cells}
    assert names == {"cell001", "cell002"}


def test_scan_cells_ignores_non_cell_dirs(mock_mount):
    cells = scan_cells([str(mock_mount)], pattern="cell*")
    names = {c.name for c in cells}
    assert "not_a_cell" not in names


def test_scan_cells_counts_datasets(mock_mount):
    cells = scan_cells([str(mock_mount)], pattern="cell*")
    cell_map = {c.name: c for c in cells}
    assert cell_map["cell001"].dataset_count == 2
    assert cell_map["cell002"].dataset_count == 1


def test_scan_cells_marks_active(mock_mount):
    cells = scan_cells([str(mock_mount)], pattern="cell*")
    assert all(c.active for c in cells)


def test_scan_cells_nonexistent_root():
    """A root that doesn't exist returns no cells (no error)."""
    cells = scan_cells(["/nonexistent/path"], pattern="cell*")
    assert cells == []


def test_get_datasets_in_cell(mock_mount):
    datasets = get_datasets_in_cell(str(mock_mount / "cell001"))
    names = {d.name for d in datasets}
    assert names == {"dataset_a", "dataset_b"}


def test_get_datasets_reads_fps(mock_mount):
    datasets = get_datasets_in_cell(str(mock_mount / "cell001"))
    assert all(d.fps == 30 for d in datasets)
```

- [ ] **Step 4: Run tests — verify they fail**

```bash
uv run pytest tests/test_cell_service.py -v 2>&1 | tail -20
```

Expected: `ModuleNotFoundError` or similar — `cell_service` doesn't exist yet.

- [ ] **Step 5: Create `backend/services/cell_service.py`**

```python
"""Service for scanning mount roots and discovering cell/dataset structure.

A "cell" is a subdirectory of an allowed_dataset_root whose name matches
the configured pattern (default: "cell*"). A dataset inside a cell is any
subdirectory that contains meta/info.json.
"""

from __future__ import annotations

import fnmatch
import json
import logging
from pathlib import Path

from backend.models.schemas import CellInfo, DatasetSummary

logger = logging.getLogger(__name__)


def scan_cells(roots: list[str], pattern: str = "cell*") -> list[CellInfo]:
    """Scan all roots for cell directories matching pattern.

    Args:
        roots: List of mount root paths (from allowed_dataset_roots).
        pattern: Glob pattern for cell directory names (default "cell*").

    Returns:
        List of CellInfo sorted by (root, name).
    """
    cells: list[CellInfo] = []
    for root_str in roots:
        root = Path(root_str)
        if not root.exists() or not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if not fnmatch.fnmatch(child.name, pattern):
                continue
            dataset_count = _count_datasets(child)
            cells.append(CellInfo(
                name=child.name,
                path=str(child.resolve()),
                mount_root=str(root.resolve()),
                dataset_count=dataset_count,
                active=True,
            ))
    return cells


def get_datasets_in_cell(cell_path: str) -> list[DatasetSummary]:
    """Return all datasets inside a cell directory.

    A dataset is a subdirectory containing meta/info.json.
    graded_count is 0 for now — computed from sidecar in a future step.
    """
    root = Path(cell_path)
    if not root.exists() or not root.is_dir():
        return []

    datasets: list[DatasetSummary] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        info_path = child / "meta" / "info.json"
        if not info_path.exists():
            continue
        try:
            info = json.loads(info_path.read_text(encoding="utf-8").rstrip("\x00"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Cannot read %s: %s", info_path, e)
            continue
        datasets.append(DatasetSummary(
            name=child.name,
            path=str(child.resolve()),
            total_episodes=info.get("total_episodes", 0),
            graded_count=0,  # populated by episode_service in a later task
            robot_type=info.get("robot_type"),
            fps=info.get("fps", 0),
        ))
    return datasets


def _count_datasets(cell_dir: Path) -> int:
    """Count subdirectories of cell_dir that have meta/info.json."""
    return sum(
        1 for child in cell_dir.iterdir()
        if child.is_dir() and (child / "meta" / "info.json").exists()
    )
```

- [ ] **Step 6: Run tests — verify they pass**

```bash
uv run pytest tests/test_cell_service.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 7: Create `backend/routers/cells.py`**

```python
"""Router for cell and dataset listing endpoints."""

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.models.schemas import CellInfo, DatasetSummary
from backend.services.cell_service import get_datasets_in_cell, scan_cells

router = APIRouter(prefix="/api/cells", tags=["cells"])


@router.get("", response_model=list[CellInfo])
async def list_cells():
    """Scan allowed_dataset_roots for cell* directories."""
    return scan_cells(settings.allowed_dataset_roots, pattern=settings.cell_name_pattern)


@router.get("/{cell_path:path}/datasets", response_model=list[DatasetSummary])
async def list_datasets_in_cell(cell_path: str):
    """List datasets inside a cell directory.

    cell_path is the full absolute path to the cell directory,
    URL-encoded by the client.
    """
    import urllib.parse
    decoded = urllib.parse.unquote(cell_path)
    datasets = get_datasets_in_cell(decoded)
    if not datasets and not __import__("pathlib").Path(decoded).exists():
        raise HTTPException(status_code=404, detail=f"Cell path not found: {decoded}")
    return datasets
```

- [ ] **Step 8: Register router in `backend/main.py`**

Add after the existing imports:
```python
from backend.routers import cells  # add this line
```

Add after the existing `app.include_router` calls:
```python
app.include_router(cells.router)
```

- [ ] **Step 9: Verify endpoints work**

```bash
uv run python -m backend.main &
sleep 2
curl -s http://localhost:8000/api/cells | python3 -m json.tool
curl -s http://localhost:8000/api/health
kill %1
```

Expected: `/api/cells` returns `[]` (no actual mounts in dev) without error.

- [ ] **Step 10: Commit**

```bash
git add backend/
git add tests/test_cell_service.py
git commit -m "feat: cell service and /api/cells router"
```

---

## Task 4: Frontend — `useCells` Hook

**Files:**
- Create: `frontend/src/hooks/useCells.ts`

- [ ] **Step 1: Create `frontend/src/hooks/useCells.ts`**

```typescript
import { useState, useCallback } from 'react'
import client from '../api/client'
import type { CellInfo, DatasetSummary } from '../types'

interface UseCellsReturn {
  cells: CellInfo[]
  loading: boolean
  error: string | null
  fetchCells: () => Promise<void>
}

interface UseDatasetsReturn {
  datasets: DatasetSummary[]
  loading: boolean
  error: string | null
  fetchDatasets: (cellPath: string) => Promise<void>
}

export function useCells(): UseCellsReturn {
  const [cells, setCells] = useState<CellInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchCells = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await client.get<CellInfo[]>('/cells')
      setCells(resp.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch cells')
    } finally {
      setLoading(false)
    }
  }, [])

  return { cells, loading, error, fetchCells }
}

export function useDatasets(): UseDatasetsReturn {
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchDatasets = useCallback(async (cellPath: string) => {
    setLoading(true)
    setError(null)
    try {
      const encoded = encodeURIComponent(cellPath)
      const resp = await client.get<DatasetSummary[]>(`/cells/${encoded}/datasets`)
      setDatasets(resp.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch datasets')
    } finally {
      setLoading(false)
    }
  }, [])

  return { datasets, loading, error, fetchDatasets }
}
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep useCells
```

Expected: no errors for `useCells.ts`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useCells.ts
git commit -m "feat: useCells and useDatasets hooks"
```

---

## Task 5: Frontend — TopNav Component

**Files:**
- Create: `frontend/src/components/TopNav.tsx`

- [ ] **Step 1: Create `frontend/src/components/TopNav.tsx`**

```tsx
import type { AppState, DatasetTab } from '../types'

interface TopNavProps {
  state: AppState
  onNavigateHome: () => void
  onNavigateCell: (cellName: string, cellPath: string) => void
  onTabChange?: (tab: DatasetTab) => void
}

const TABS: { id: DatasetTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'curate',   label: 'Curate' },
  { id: 'fields',   label: 'Fields' },
  { id: 'ops',      label: 'Ops' },
]

export function TopNav({ state, onNavigateHome, onNavigateCell, onTabChange }: TopNavProps) {
  return (
    <nav className="top-nav">
      <button className="top-nav-logo" onClick={onNavigateHome}>
        robo<span>data</span>
      </button>

      <div className="top-nav-breadcrumb">
        {state.view !== 'library' && (
          <>
            <span className="sep">/</span>
            <button onClick={() => {
              if (state.view === 'cell' || state.view === 'dataset') {
                onNavigateCell(state.cellName, state.cellPath)
              }
            }}>
              <em>{state.view === 'cell' || state.view === 'dataset' ? state.cellName : ''}</em>
            </button>
          </>
        )}
        {state.view === 'dataset' && (
          <>
            <span className="sep">/</span>
            <em>{state.datasetName}</em>
          </>
        )}
      </div>

      {state.view === 'dataset' && onTabChange && (
        <div className="top-nav-tabs">
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`top-nav-tab${state.tab === tab.id ? ' active' : ''}`}
              onClick={() => onTabChange(tab.id)}
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

- [ ] **Step 2: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep TopNav
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TopNav.tsx
git commit -m "feat: TopNav component"
```

---

## Task 6: Frontend — LibraryPage + CellPage

**Files:**
- Create: `frontend/src/components/LibraryPage.tsx`
- Create: `frontend/src/components/CellPage.tsx`

- [ ] **Step 1: Create `frontend/src/components/LibraryPage.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useCells } from '../hooks/useCells'
import type { CellInfo } from '../types'

interface LibraryPageProps {
  onSelectCell: (cell: CellInfo) => void
}

export function LibraryPage({ onSelectCell }: LibraryPageProps) {
  const { cells, loading, error, fetchCells } = useCells()
  const [search, setSearch] = useState('')

  useEffect(() => { void fetchCells() }, [fetchCells])

  const filtered = cells.filter(c =>
    c.name.toLowerCase().includes(search.toLowerCase())
  )

  // Group by mount_root
  const byRoot = filtered.reduce<Record<string, CellInfo[]>>((acc, cell) => {
    if (!acc[cell.mount_root]) acc[cell.mount_root] = []
    acc[cell.mount_root].push(cell)
    return acc
  }, {})

  return (
    <div className="library-page">
      <div className="library-filter-bar">
        <input
          className="library-search"
          placeholder="Search cells..."
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
      </div>

      {loading && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Scanning mounts...</div>}
      {error && <div style={{ color: 'var(--c-red)', fontSize: 12 }}>{error}</div>}

      {Object.entries(byRoot).map(([root, rootCells]) => (
        <div key={root}>
          <div className="library-section-header">{root}</div>
          <div className="cell-grid">
            {rootCells.map(cell => (
              <div
                key={cell.path}
                className="cell-card"
                onClick={() => onSelectCell(cell)}
              >
                <div className="cell-card-name">
                  <span className={`cell-status-dot ${cell.active ? 'active' : 'idle'}`} />
                  {cell.name}
                </div>
                <div className="cell-card-meta">
                  {cell.dataset_count} dataset{cell.dataset_count !== 1 ? 's' : ''}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {!loading && cells.length === 0 && (
        <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '20px 0' }}>
          No cells found. Check <code>CURATION_ALLOWED_DATASET_ROOTS</code> config.
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Create `frontend/src/components/CellPage.tsx`**

```tsx
import { useEffect } from 'react'
import { useDatasets } from '../hooks/useCells'
import type { DatasetSummary } from '../types'

interface CellPageProps {
  cellName: string
  cellPath: string
  onSelectDataset: (dataset: DatasetSummary) => void
}

export function CellPage({ cellName, cellPath, onSelectDataset }: CellPageProps) {
  const { datasets, loading, error, fetchDatasets } = useDatasets()

  useEffect(() => { void fetchDatasets(cellPath) }, [cellPath, fetchDatasets])

  return (
    <div className="cell-page">
      <div style={{ marginBottom: 16, fontSize: 12, color: 'var(--text-muted)' }}>
        {datasets.length} dataset{datasets.length !== 1 ? 's' : ''} in {cellName}
      </div>

      {loading && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading...</div>}
      {error && <div style={{ color: 'var(--c-red)', fontSize: 12 }}>{error}</div>}

      <div className="dataset-grid">
        {datasets.map(ds => {
          const pct = ds.total_episodes > 0
            ? Math.round((ds.graded_count / ds.total_episodes) * 100)
            : 0
          const fillColor = pct === 100 ? 'var(--c-green)' : 'var(--accent)'

          return (
            <div
              key={ds.path}
              className="dataset-card"
              onClick={() => onSelectDataset(ds)}
            >
              {ds.robot_type && (
                <div style={{ fontSize: 9, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>
                  {ds.robot_type}
                </div>
              )}
              <div className="dataset-card-name">{ds.name}</div>
              <div className="dataset-card-meta">
                <span>{ds.total_episodes} eps</span>
                <span>{ds.fps} fps</span>
              </div>
              <div className="dataset-card-progress">
                <div
                  className="dataset-card-progress-fill"
                  style={{ width: `${pct}%`, background: fillColor }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/LibraryPage.tsx frontend/src/components/CellPage.tsx
git commit -m "feat: LibraryPage and CellPage components"
```

---

## Task 7: Frontend — App.tsx State Machine

**Files:**
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/components/DatasetPage.tsx` (stub)

- [ ] **Step 1: Create stub `frontend/src/components/DatasetPage.tsx`**

This is a temporary stub. The full Curate/Ops tabs are wired in Tasks 8-10.

```tsx
import type { DatasetTab, DatasetInfo, Episode } from '../types'

interface DatasetPageProps {
  datasetPath: string
  datasetName: string
  tab: DatasetTab
}

export function DatasetPage({ datasetPath, datasetName, tab }: DatasetPageProps) {
  return (
    <div style={{ padding: 20, color: 'var(--text-muted)', fontSize: 12 }}>
      <div>Dataset: <strong style={{ color: 'var(--text)' }}>{datasetName}</strong></div>
      <div>Path: <code>{datasetPath}</code></div>
      <div style={{ marginTop: 12 }}>Tab: {tab} (coming soon)</div>
    </div>
  )
}
```

- [ ] **Step 2: Rewrite `frontend/src/App.tsx`**

```tsx
import { useCallback } from 'react'
import { TopNav } from './components/TopNav'
import { LibraryPage } from './components/LibraryPage'
import { CellPage } from './components/CellPage'
import { DatasetPage } from './components/DatasetPage'
import { useAppState } from './hooks/useAppState'
import type { CellInfo, DatasetSummary } from './types'
import './App.css'

export default function App() {
  const { state, navigateHome, navigateToCell, navigateToDataset, setTab } = useAppState()

  const handleSelectCell = useCallback((cell: CellInfo) => {
    navigateToCell(cell.name, cell.path)
  }, [navigateToCell])

  const handleSelectDataset = useCallback((ds: DatasetSummary) => {
    if (state.view === 'cell') {
      navigateToDataset(state.cellName, state.cellPath, ds.path, ds.name)
    }
  }, [state, navigateToDataset])

  return (
    <div className="app-root">
      <TopNav
        state={state}
        onNavigateHome={navigateHome}
        onNavigateCell={navigateToCell}
        onTabChange={setTab}
      />
      <div className="page-content">
        {state.view === 'library' && (
          <LibraryPage onSelectCell={handleSelectCell} />
        )}
        {state.view === 'cell' && (
          <CellPage
            cellName={state.cellName}
            cellPath={state.cellPath}
            onSelectDataset={handleSelectDataset}
          />
        )}
        {state.view === 'dataset' && (
          <DatasetPage
            datasetPath={state.datasetPath}
            datasetName={state.datasetName}
            tab={state.tab}
          />
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Create `frontend/src/hooks/useAppState.ts`**

```typescript
import { useState, useCallback } from 'react'
import type { AppState, DatasetTab } from '../types'

interface UseAppStateReturn {
  state: AppState
  navigateHome: () => void
  navigateToCell: (cellName: string, cellPath: string) => void
  navigateToDataset: (cellName: string, cellPath: string, datasetPath: string, datasetName: string) => void
  setTab: (tab: DatasetTab) => void
}

export function useAppState(): UseAppStateReturn {
  const [state, setState] = useState<AppState>({ view: 'library' })

  const navigateHome = useCallback(() => {
    setState({ view: 'library' })
  }, [])

  const navigateToCell = useCallback((cellName: string, cellPath: string) => {
    setState({ view: 'cell', cellName, cellPath })
  }, [])

  const navigateToDataset = useCallback((
    cellName: string,
    cellPath: string,
    datasetPath: string,
    datasetName: string,
  ) => {
    setState({ view: 'dataset', cellName, cellPath, datasetPath, datasetName, tab: 'curate' })
  }, [])

  const setTab = useCallback((tab: DatasetTab) => {
    setState(prev =>
      prev.view === 'dataset' ? { ...prev, tab } : prev
    )
  }, [])

  return { state, navigateHome, navigateToCell, navigateToDataset, setTab }
}
```

- [ ] **Step 4: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -30
```

Expected: errors only from components still using old `GRADE_COLORS` — fixed in Tasks 8-9.

- [ ] **Step 5: Start dev server and verify navigation works**

```bash
cd frontend && npm run dev &
# Open http://localhost:5173
# Should show: robodata logo, library page with "No cells found" message
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/
git commit -m "feat: 3-level App state machine with TopNav"
```

---

## Task 8: EpisodeList Restyle

**Files:**
- Modify: `frontend/src/components/EpisodeList.tsx`

- [ ] **Step 1: Read the current file**

```bash
cat frontend/src/components/EpisodeList.tsx
```

- [ ] **Step 2: Rewrite `frontend/src/components/EpisodeList.tsx`**

The grade dot replaces the colored text badge. All inline styles replaced by CSS classes from App.css.

```tsx
import type { Episode } from '../types'

interface EpisodeListProps {
  episodes: Episode[]
  loading: boolean
  error: string | null
  onEpisodeSelect: (episode: Episode) => void
  selectedIndex: number | null
}

function gradeDotClass(grade: string | null): string {
  if (grade === 'good')   return 'good'
  if (grade === 'normal') return 'normal'
  if (grade === 'bad')    return 'bad'
  return 'none'
}

export function EpisodeList({
  episodes, loading, error, onEpisodeSelect, selectedIndex,
}: EpisodeListProps) {
  const gradedCount = episodes.filter(e => e.grade).length

  return (
    <>
      <div className="episode-sidebar-header">
        <span className="episode-sidebar-title">Episodes</span>
        <span className="episode-progress-count">{gradedCount} / {episodes.length}</span>
      </div>

      {loading && (
        <div style={{ padding: '10px', fontSize: 11, color: 'var(--text-muted)' }}>
          Loading...
        </div>
      )}
      {error && (
        <div style={{ padding: '10px', fontSize: 11, color: 'var(--c-red)' }}>
          {error}
        </div>
      )}

      <div className="episode-list">
        {episodes.map(ep => (
          <div
            key={ep.episode_index}
            className={`episode-item${ep.episode_index === selectedIndex ? ' active' : ''}`}
            onClick={() => onEpisodeSelect(ep)}
          >
            <span className={`episode-grade-dot ${gradeDotClass(ep.grade)}`} />
            <span className="episode-item-idx">ep_{String(ep.episode_index).padStart(3, '0')}</span>
            <span className="episode-item-len">{ep.length}f</span>
          </div>
        ))}
        {!loading && episodes.length === 0 && (
          <div style={{ padding: '10px', fontSize: 11, color: 'var(--text-muted)' }}>
            No episodes found.
          </div>
        )}
      </div>
    </>
  )
}
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep EpisodeList
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/EpisodeList.tsx
git commit -m "refactor: EpisodeList — grade dots, CSS variables"
```

---

## Task 9: D1 Grade UI in EpisodeEditor

**Files:**
- Modify: `frontend/src/components/EpisodeEditor.tsx`

- [ ] **Step 1: Rewrite `frontend/src/components/EpisodeEditor.tsx`**

Removes `GRADE_COLORS` usage. Grade bar moves to the center panel (wired in Task 10). The editor now only shows details + tags.

```tsx
import { useState, useEffect } from 'react'
import type { Episode } from '../types'

interface EpisodeEditorProps {
  episode: Episode | null
  onSave: (index: number, grade: string | null, tags: string[]) => Promise<void>
}

export function EpisodeEditor({ episode, onSave }: EpisodeEditorProps) {
  const [tags, setTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (episode) {
      setTags(episode.tags)
      setTagInput('')
    }
  }, [episode?.episode_index])

  const saveTags = async (newTags: string[]) => {
    if (!episode) return
    setSaving(true)
    try {
      await onSave(episode.episode_index, episode.grade, newTags)
    } finally {
      setSaving(false)
    }
  }

  const addTag = (tag: string) => {
    const t = tag.trim()
    if (!t || tags.includes(t)) return
    const next = [...tags, t]
    setTags(next)
    void saveTags(next)
  }

  const removeTag = (tag: string) => {
    const next = tags.filter(t => t !== tag)
    setTags(next)
    void saveTags(next)
  }

  if (!episode) {
    return (
      <div className="ep-details" style={{ color: 'var(--text-muted)', fontSize: 12 }}>
        Select an episode
      </div>
    )
  }

  return (
    <div className="ep-details">
      <div className="ep-details-row">
        <span className="ep-details-key">episode</span>
        <span className="ep-details-val" style={{ color: 'var(--accent)' }}>
          ep_{String(episode.episode_index).padStart(3, '0')}
        </span>
      </div>
      <div className="ep-details-row">
        <span className="ep-details-key">length</span>
        <span className="ep-details-val">{episode.length} frames</span>
      </div>
      <div className="ep-details-row">
        <span className="ep-details-key">task</span>
        <span className="ep-details-val" style={{ maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {episode.task_instruction || `task_${episode.task_index}`}
        </span>
      </div>
      <div className="ep-details-row">
        <span className="ep-details-key">grade</span>
        <span className="ep-details-val" style={{
          color: episode.grade === 'good' ? 'var(--c-green)'
               : episode.grade === 'normal' ? 'var(--c-yellow)'
               : episode.grade === 'bad' ? 'var(--c-red)'
               : 'var(--text-dim)',
        }}>
          {episode.grade ?? '—'}
        </span>
      </div>
      {saving && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>saving...</div>}

      {/* Tags */}
      <div style={{ marginTop: 10 }}>
        <div style={{ fontSize: 9, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 5 }}>Tags</div>
        <div className="tag-chips">
          {tags.map(tag => (
            <span key={tag} className="tag-chip">
              {tag}
              <button className="tag-chip-remove" onClick={() => removeTag(tag)}>×</button>
            </span>
          ))}
          <button
            className="tag-add-chip"
            onClick={() => {
              const t = prompt('Tag:')
              if (t) addTag(t)
            }}
          >
            + add
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -E "GRADE_COLORS|EpisodeEditor"
```

Expected: no errors related to `GRADE_COLORS` or `EpisodeEditor`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/EpisodeEditor.tsx
git commit -m "refactor: EpisodeEditor — D1 grade display, remove GRADE_COLORS"
```

---

## Task 10: Wire Up Curate Tab in DatasetPage

**Files:**
- Modify: `frontend/src/components/DatasetPage.tsx`

The Curate tab integrates the existing `VideoPlayer`, `ScalarChart`, `EpisodeList`, `EpisodeEditor`, `TaskEditor`, `SplitMergePanel` with the new CSS classes and D1 grade bar.

- [ ] **Step 1: Rewrite `frontend/src/components/DatasetPage.tsx`**

```tsx
import { useState, useCallback, useEffect, useRef } from 'react'
import { EpisodeList } from './EpisodeList'
import { EpisodeEditor } from './EpisodeEditor'
import { TaskEditor } from './TaskEditor'
import { VideoPlayer, type VideoPlayerHandle } from './VideoPlayer'
import { ScalarChart } from './ScalarChart'
import { SplitMergePanel } from './SplitMergePanel'
import { useDataset } from '../hooks/useDataset'
import { useEpisodes } from '../hooks/useEpisodes'
import type { DatasetTab, DatasetInfo, Episode } from '../types'

interface DatasetPageProps {
  datasetPath: string
  datasetName: string
  tab: DatasetTab
}

const GRADE_KEYS: Record<string, string> = { '1': 'good', '2': 'normal', '3': 'bad' }

export function DatasetPage({ datasetPath, datasetName, tab }: DatasetPageProps) {
  const { dataset, loading: dsLoading, loadDataset } = useDataset()
  const { episodes, loading: epLoading, error: epError, fetchEpisodes, updateEpisode } = useEpisodes()
  const [selectedEpisode, setSelectedEpisode] = useState<Episode | null>(null)
  const [currentFrame, setCurrentFrame] = useState(0)
  const [terminalFrames, setTerminalFrames] = useState<number[]>([])
  const [terminalTimestamps, setTerminalTimestamps] = useState<number[]>([])
  const [rightTab, setRightTab] = useState<'details' | 'splitmerge'>('details')
  const videoRef = useRef<VideoPlayerHandle>(null)

  // Load dataset when path changes
  useEffect(() => {
    void loadDataset(datasetPath).then(() => fetchEpisodes())
  }, [datasetPath])

  const handleSaveEpisode = useCallback(async (index: number, grade: string | null, tags: string[]) => {
    await updateEpisode(index, grade, tags)
    if (grade) {
      const currentIdx = episodes.findIndex(e => e.episode_index === index)
      const nextUngraded = episodes.find((e, i) => i > currentIdx && !e.grade)
        ?? episodes.find((e, i) => i < currentIdx && !e.grade)
      if (nextUngraded) {
        setSelectedEpisode(nextUngraded)
        return
      }
    }
    setSelectedEpisode(prev =>
      prev?.episode_index === index ? { ...prev, grade, tags } : prev
    )
  }, [updateEpisode, episodes])

  const navigateEpisode = useCallback((direction: -1 | 1) => {
    if (!selectedEpisode || episodes.length === 0) return
    const idx = episodes.findIndex(e => e.episode_index === selectedEpisode.episode_index)
    const next = episodes[idx + direction]
    if (next) setSelectedEpisode(next)
  }, [selectedEpisode, episodes])

  const quickGrade = useCallback(async (key: string) => {
    if (!selectedEpisode) return
    const grade = GRADE_KEYS[key]
    if (grade) await handleSaveEpisode(selectedEpisode.episode_index, grade, selectedEpisode.tags)
  }, [selectedEpisode, handleSaveEpisode])

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      switch (e.key) {
        case 'ArrowUp': case 'k':   e.preventDefault(); navigateEpisode(-1); break
        case 'ArrowDown': case 'j': e.preventDefault(); navigateEpisode(1); break
        case 'ArrowLeft':  e.preventDefault(); videoRef.current?.stepFrame(-1); break
        case 'ArrowRight': e.preventDefault(); videoRef.current?.stepFrame(1); break
        case '1': case '2': case '3': e.preventDefault(); void quickGrade(e.key); break
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [navigateEpisode, quickGrade])

  if (tab !== 'curate' && tab !== 'ops') {
    return (
      <div style={{ padding: 20, color: 'var(--text-muted)', fontSize: 12 }}>
        {tab === 'overview' && 'Overview tab — coming in Plan B'}
        {tab === 'fields' && 'Fields tab — coming in Plan B'}
      </div>
    )
  }

  return (
    <div className="dataset-page">
      <div className="curate-layout">
        {/* Left: episode list */}
        <div className="episode-sidebar">
          <EpisodeList
            episodes={episodes}
            loading={epLoading}
            error={epError}
            onEpisodeSelect={setSelectedEpisode}
            selectedIndex={selectedEpisode?.episode_index ?? null}
          />
        </div>

        {/* Center: video + grade */}
        <div className="curate-center">
          <VideoPlayer
            ref={videoRef}
            episodeIndex={selectedEpisode?.episode_index ?? null}
            fps={dataset?.fps ?? 30}
            onFrameChange={setCurrentFrame}
            terminalFrames={terminalFrames}
          />

          {/* Scrubber rendered by VideoPlayer internally */}

          {/* Terminal frames */}
          {selectedEpisode && terminalFrames.length > 0 && (
            <div className="terminal-bar">
              <span className="terminal-bar-label">Terminal ({terminalFrames.length}):</span>
              {terminalFrames.map((f, i) => {
                const ts = terminalTimestamps[i]
                const label = ts != null ? `${ts.toFixed(2)}s` : `f${f}`
                return (
                  <button
                    key={i}
                    className={`terminal-frame-chip${currentFrame === f ? ' active' : ''}`}
                    onClick={() => ts != null
                      ? videoRef.current?.seekToTimestamp(ts)
                      : videoRef.current?.seekToFrame(f)
                    }
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          )}

          {/* D1 Grade bar */}
          {selectedEpisode && (
            <div className="grade-bar">
              {(['good', 'normal', 'bad'] as const).map(g => (
                <button
                  key={g}
                  className={`grade-btn${selectedEpisode.grade === g ? ' active' : ''}`}
                  onClick={() => handleSaveEpisode(selectedEpisode.episode_index, g, selectedEpisode.tags)}
                >
                  {g}
                </button>
              ))}
              <div className="grade-kbd-hint">
                <kbd>1</kbd><kbd>2</kbd><kbd>3</kbd>
              </div>
            </div>
          )}
        </div>

        {/* Right: details / split-merge */}
        <div className="curate-right">
          <div className="right-tabs">
            <button
              className={`right-tab${rightTab === 'details' ? ' active' : ''}`}
              onClick={() => setRightTab('details')}
            >
              Details
            </button>
            <button
              className={`right-tab${rightTab === 'splitmerge' ? ' active' : ''}`}
              onClick={() => setRightTab('splitmerge')}
            >
              Split/Merge
            </button>
          </div>

          {rightTab === 'details' && (
            <>
              <EpisodeEditor episode={selectedEpisode} onSave={handleSaveEpisode} />
              <TaskEditor episode={selectedEpisode} />
              <ScalarChart
                episodeIndex={selectedEpisode?.episode_index ?? null}
                currentFrame={currentFrame}
                onTerminalFrames={(frames, timestamps) => {
                  setTerminalFrames(frames)
                  setTerminalTimestamps(timestamps)
                }}
              />
            </>
          )}
          {rightTab === 'splitmerge' && (
            <SplitMergePanel
              datasetPath={dataset?.path ?? null}
              episodes={episodes}
            />
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Update `useDataset` hook to accept a path parameter**

Check the current `useDataset` hook:

```bash
cat frontend/src/hooks/useDataset.ts
```

If `loadDataset` already accepts a path string, no change needed. If it reads from state, add a `loadDataset(path: string)` overload. The existing hook should work as-is since `DatasetLoader` already calls `loadDataset(path)`.

- [ ] **Step 3: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: zero errors (or only errors in files not yet touched).

- [ ] **Step 4: Start dev server and verify full flow**

```bash
cd frontend && npm run dev
# Also start backend:
uv run python -m backend.main
```

Test:
1. Library page loads (shows "No cells found" or real cells)
2. Click a cell → CellPage with dataset cards
3. Click a dataset → DatasetPage loads with Curate tab
4. Episodes load, video plays, grade bar shows with D1 style
5. Press `1`/`2`/`3` to grade — episode advances
6. Grade dots update in episode list

- [ ] **Step 5: Run backend tests**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Final commit**

```bash
git add frontend/src/
git commit -m "feat: wire DatasetPage Curate tab with D1 grade UI"
```

---

## Task 11: ScalarChart Color Update

**Files:**
- Modify: `frontend/src/components/ScalarChart.tsx`

The ScalarChart currently uses hardcoded hex colors. Update to use the design token palette.

- [ ] **Step 1: Update COLORS array in `frontend/src/components/ScalarChart.tsx`**

Find the line:
```typescript
const COLORS = [
  '#4fc3f7', '#81c784', '#ffb74d', ...
]
```

Replace with:
```typescript
const COLORS = [
  '#5794f2', '#73bf69', '#fade2a', '#f08080', '#b877d9',
  '#ff9830', '#37aee2', '#7fb77e', '#e8a838', '#e07070',
  '#9c6ede', '#dd8040', '#4dbfa8', '#9fb04a', '#d06088',
]
```

- [ ] **Step 2: Update section header background in ScalarChart**

Find `background: '#161616'` and `background: '#111'` inline styles — replace with `var(--panel)` and `var(--bg)` respectively.

Find the `chartStyles` object and update:
```typescript
const chartStyles: Record<string, React.CSSProperties> = {
  container: { display: 'flex', flexDirection: 'column', overflow: 'visible', flexShrink: 0 },
  loading: { padding: '12px', fontSize: '11px', color: 'var(--text-muted)' as string },
  error: { padding: '12px', fontSize: '11px', color: 'var(--c-red)' as string },
  section: { borderBottom: '1px solid var(--border)' as string },
  sectionHeader: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '6px 12px', cursor: 'pointer',
    background: 'var(--panel)' as string,
    borderBottom: '1px solid var(--border2)' as string,
  },
  sectionTitle: { fontSize: '10px', fontWeight: 600, textTransform: 'uppercase' as const, letterSpacing: '0.06em', color: 'var(--text-dim)' as string },
  sectionCount: { fontSize: '10px', color: 'var(--text-dim)' as string, fontFamily: 'monospace' },
  chartItem: { padding: '3px 12px', borderBottom: '1px solid #1a1a1a' },
  chartHeader: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '2px' },
  chartLabel: { fontSize: '10px', fontFamily: 'monospace', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const, maxWidth: '180px' },
  chartValue: { fontSize: '10px', fontFamily: 'monospace', color: 'var(--text-muted)' as string },
  canvas: { width: '100%', height: '40px', borderRadius: '2px' },
}
```

Also update the canvas background in `MiniChart` useEffect:
```typescript
// Background
ctx.fillStyle = 'var(--bg)'   // won't work in canvas — use literal:
ctx.fillStyle = '#0f0f0f'
// Grid lines
ctx.strokeStyle = '#1e1e1e'
```

- [ ] **Step 3: Run TypeScript check and visually verify**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep ScalarChart
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ScalarChart.tsx
git commit -m "refactor: ScalarChart — Grafana palette colors"
```

---

## Completion Check

- [ ] **Run all backend tests**

```bash
uv run pytest -v
```

Expected: all tests pass.

- [ ] **Run frontend type check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Manual smoke test**

1. Backend starts: `uv run python -m backend.main`
2. Frontend starts: `cd frontend && npm run dev`
3. Library page renders at http://localhost:5173
4. Navigate Library → Cell → Dataset → Curate tab
5. Episodes load, video plays, D1 grade bar works
6. Keyboard shortcuts `1`/`2`/`3`/`↑`/`↓` work
7. ScalarChart renders with Grafana palette
8. No blue/Catppuccin colors visible anywhere

---

*Plan B (`2026-04-14-robodata-studio-plan-b.md`) covers Overview tab (distribution visualization) and Fields tab (parquet column + info.json editing).*
