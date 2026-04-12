# Conversion Pipeline Page — Design Spec

**Date:** 2026-04-12  
**Status:** Approved

## Overview

Add a new Conversion tab to the existing curation_tools web app. The page allows users to configure and run a rosbag (MCAP) → LeRobot v3.0 dataset conversion pipeline, with both manual and automatic (file-watching) modes. Configuration is saved as named profiles and loaded on demand.

---

## 1. Architecture

```
Frontend (React)                    Backend (FastAPI)
────────────────                    ──────────────────────────────────────
[Conversion Tab] [Curation Tab]     /api/conversion/
                                      configs  (CRUD for named profiles)
ConversionPage                        watch/start, watch/stop
  ├── ConfigPanel (left)              run         (manual trigger)
  │   ├── Config Profile selector     jobs        (list + SSE stream)
  │   ├── Input Path
  │   ├── HF Repo selector        backend/routers/conversion.py
  │   ├── Task Name / FPS         backend/services/conversion_service.py
  │   ├── Camera Topics (k/v)
  │   ├── Joint Names (tags)      conversion_configs/{name}.json
  │   ├── Task Instructions (list)    (profiles stored in project root)
  │   └── Save Config button
  └── StatusPanel (right)
      ├── Auto Watch toggle
      ├── Run Once / Stop buttons
      ├── Active Jobs (progress bar)
      └── Recent History
```

Navigation: top tab bar, **Conversion first**, Curation second. No react-router; state-based page switching in `App.tsx`.

---

## 2. Frontend

### New Files
- `frontend/src/components/ConversionPage.tsx` — top-level page, composes ConfigPanel + StatusPanel
- `frontend/src/components/conversion/ConfigPanel.tsx` — left panel with all config fields
- `frontend/src/components/conversion/StatusPanel.tsx` — right panel with watch control and job list
- `frontend/src/hooks/useConversion.ts` — API calls for configs and jobs

### App.tsx Changes
- Add `activePage: 'conversion' | 'curation'` state
- Render top tab bar before the existing 3-panel layout
- Conditionally render `<ConversionPage>` or existing curation layout

### Config Profile UI
- Dropdown at top of ConfigPanel listing saved profiles
- **New** button → prompt for profile name → save current fields
- **Delete** button → delete selected profile
- On profile select → populate all fields from saved config

### Config Fields
| Field | UI Component |
|-------|-------------|
| Input Path | Text input (typed manually; no server-side file browser) |
| HF Repository | List of mounted repos (radio select) + "Create new" option |
| Task Name | Text input |
| FPS | Number input |
| Camera Topics | Key→Value row list with add/delete |
| Joint Names | Tag chip list with add/delete |
| Task Instructions | String row list with add/delete |

### Status Panel
- **Auto Watch toggle** — shows "Watching" / "Stopped" state with colored indicator
- **Run Once** button — triggers manual conversion run
- **Stop** button — cancels active watch / running job
- **Active Jobs** — list with progress bar + status badge (Converting / Queued)
- **Recent History** — last N jobs with outcome (Done → processed/ / Failed + reason)

### Real-time Updates
- SSE connection to `GET /api/conversion/jobs/stream` while page is visible
- Updates active job progress and history list without polling

---

## 3. Backend

### New Files
- `backend/routers/conversion.py`
- `backend/services/conversion_service.py`

### API Endpoints

```
GET    /api/conversion/configs              List all saved profile names + contents
POST   /api/conversion/configs              Create new profile  { name, config }
PUT    /api/conversion/configs/{name}       Update existing profile
DELETE /api/conversion/configs/{name}       Delete profile

GET    /api/conversion/watch/status         Current watch state + active input_path
POST   /api/conversion/watch/start          Start watchdog  { profile_name }
POST   /api/conversion/watch/stop           Stop watchdog

POST   /api/conversion/run                  Manual one-shot run  { profile_name }

GET    /api/conversion/jobs                 List active + recent history (last 50)
GET    /api/conversion/jobs/stream          SSE stream of job updates
```

### Config Profile Storage
- Directory: `{project_root}/conversion_configs/`
- One file per profile: `{name}.json`
- File content mirrors rosbag-to-lerobot `config.json` schema plus `input_path` field

### HF Repository Selection
- Mounted repo list fetched by reusing existing `GET /api/hf-sync/repos` endpoint (no new endpoint needed)
- Selecting a repo sets two values in the config profile:
  - `repo_id` → HF Hub identifier (e.g. `psedulab/aic_task`) passed to rosbag-to-lerobot for push-to-hub
  - `output_path` → local mount path (e.g. `/mnt/hf/aic_task`) used as the conversion output directory
- "Create new" option calls the existing HF sync mount flow to create + mount a new repo

### rosbag-to-lerobot Integration
- At service init: add `/home/weed/psedulab/rosbag-to-lerobot/src` to `sys.path`
- Import `run_conversion` function from `main.py`
- Call signature: `run_conversion(config_dict, input_dir=input_path, output_dir=output_path)`
- Run in `ThreadPoolExecutor` (single worker) — one conversion at a time, others queue
- Progress reported via a shared `queue.Queue` that `conversion_service` drains into job state

### Watchdog
- Library: `watchdog` (add to `pyproject.toml`)
- Observer monitors `input_path` for new subdirectories containing `*.mcap` files
- Debounce: wait 2s after last file event before queuing (handles in-progress copies)
- Skip folders already in job set (deduplication)
- Skip `processed/` subdirectory

### Post-Conversion Move
- On success: `shutil.move(folder, input_path / "processed" / folder.name)`
- Create `processed/` if it does not exist
- On failure: leave folder in place, record error message in job history

### Job State (in-memory)
```python
@dataclass
class ConversionJob:
    id: str           # uuid
    folder: str       # episode folder name
    status: Literal["queued", "converting", "done", "failed"]
    progress: int     # 0-100
    message: str      # current step or error
    created_at: datetime
    finished_at: Optional[datetime]
```

History capped at 100 entries (in-memory, reset on server restart).

---

## 4. Error Handling

| Scenario | Behavior |
|----------|----------|
| Conversion raises exception | Job → `failed`, message = exception string; folder stays in input_path |
| Same folder detected twice | Deduplicated via job set; second event ignored |
| SSE client disconnects | Conversion continues in background; client reconnects and gets current state |
| Watchdog target path missing | `watch/start` returns 400 with clear error message |
| rosbag-to-lerobot import fails | Service startup logs error; `/run` and `/watch/start` return 500 with explanation |
| HF repo not mounted | Config saves fine; error surfaces at conversion time when LeRobot tries to write |

---

## 5. Dependencies

Add to `pyproject.toml`:
- `watchdog` — filesystem event monitoring

No frontend package additions required (SSE via native `EventSource` API).

---

## 6. Out of Scope

- Persistent job history across server restarts (in-memory only)
- Parallel conversion of multiple folders simultaneously
- Editing `metacard.json` per-episode overrides from the UI
- Merge mode (`--merge` flag) — convert only, no merge support in initial version
