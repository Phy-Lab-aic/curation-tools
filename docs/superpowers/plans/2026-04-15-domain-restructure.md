# Backend Domain Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure flat backend into domain-based modules (`core/`, `datasets/`, `converter/`) without breaking any functionality.

**Architecture:** Move `config.py` into `backend/core/` with storage abstraction interfaces. Reorganize all dataset-related services/routers/schemas into `backend/datasets/`. Isolate converter into `backend/converter/`. Use re-export shims at old paths so tests pass immediately, then update test imports and remove shims.

**Tech Stack:** Python 3.10+, FastAPI, PyArrow, Pydantic

---

## File Structure

### New directories and files to create

```
backend/
  core/
    __init__.py                          # empty
    config.py                            # moved from backend/config.py
    storage/
      __init__.py                        # re-exports StorageBackend, LocalStorage
      base.py                            # ABC StorageBackend
      local.py                           # LocalStorage (filesystem)
  datasets/
    __init__.py                          # empty
    schemas.py                           # all dataset/episode/cell schemas from models/schemas.py
    routers/
      __init__.py                        # empty
      datasets.py                        # moved from backend/routers/datasets.py
      episodes.py                        # moved from backend/routers/episodes.py
      tasks.py                           # moved from backend/routers/tasks.py
      videos.py                          # moved from backend/routers/videos.py
      scalars.py                         # moved from backend/routers/scalars.py
      distribution.py                    # moved from backend/routers/distribution.py
      fields.py                          # moved from backend/routers/fields.py
      dataset_ops.py                     # moved from backend/routers/dataset_ops.py
      cells.py                           # moved from backend/routers/cells.py
      rerun.py                           # moved from backend/routers/rerun.py
    services/
      __init__.py                        # empty
      dataset_service.py                 # moved from backend/services/dataset_service.py
      episode_service.py                 # moved from backend/services/episode_service.py
      task_service.py                    # moved from backend/services/task_service.py
      export_service.py                  # moved from backend/services/export_service.py
      distribution_service.py            # moved from backend/services/distribution_service.py
      fields_service.py                  # moved from backend/services/fields_service.py
      dataset_ops_service.py             # moved from backend/services/dataset_ops_service.py
      cell_service.py                    # moved from backend/services/cell_service.py
      rerun_service.py                   # moved from backend/services/rerun_service.py
  converter/
    __init__.py                          # empty
    router.py                            # moved from backend/routers/converter.py
    service.py                           # moved from backend/services/converter_service.py
```

### Files to convert into re-export shims (backwards compat)

```
backend/config.py                        # re-exports from backend.core.config
backend/models/schemas.py                # re-exports from backend.datasets.schemas
backend/services/dataset_service.py      # re-exports from backend.datasets.services.dataset_service
backend/services/episode_service.py      # re-exports from backend.datasets.services.episode_service
backend/services/task_service.py         # re-exports from backend.datasets.services.task_service
backend/services/export_service.py       # re-exports from backend.datasets.services.export_service
backend/services/distribution_service.py # re-exports from backend.datasets.services.distribution_service
backend/services/fields_service.py       # re-exports from backend.datasets.services.fields_service
backend/services/dataset_ops_service.py  # re-exports from backend.datasets.services.dataset_ops_service
backend/services/cell_service.py         # re-exports from backend.datasets.services.cell_service
backend/services/rerun_service.py        # re-exports from backend.datasets.services.rerun_service
backend/services/converter_service.py    # re-exports from backend.converter.service
backend/routers/datasets.py              # re-exports from backend.datasets.routers.datasets
backend/routers/episodes.py              # re-exports from backend.datasets.routers.episodes
backend/routers/tasks.py                 # re-exports from backend.datasets.routers.tasks
backend/routers/videos.py               # re-exports from backend.datasets.routers.videos
backend/routers/scalars.py              # re-exports from backend.datasets.routers.scalars
backend/routers/distribution.py         # re-exports from backend.datasets.routers.distribution
backend/routers/fields.py               # re-exports from backend.datasets.routers.fields
backend/routers/dataset_ops.py          # re-exports from backend.datasets.routers.dataset_ops
backend/routers/cells.py                # re-exports from backend.datasets.routers.cells
backend/routers/rerun.py                # re-exports from backend.datasets.routers.rerun
backend/routers/converter.py            # re-exports from backend.converter.router
```

### Import remapping (internal — new files use new paths)

| Old import | New import |
|---|---|
| `backend.config` | `backend.core.config` |
| `backend.models.schemas` | `backend.datasets.schemas` |
| `backend.services.dataset_service` | `backend.datasets.services.dataset_service` |
| `backend.services.episode_service` | `backend.datasets.services.episode_service` |
| `backend.services.task_service` | `backend.datasets.services.task_service` |
| `backend.services.export_service` | `backend.datasets.services.export_service` |
| `backend.services.distribution_service` | `backend.datasets.services.distribution_service` |
| `backend.services.fields_service` | `backend.datasets.services.fields_service` |
| `backend.services.dataset_ops_service` | `backend.datasets.services.dataset_ops_service` |
| `backend.services.cell_service` | `backend.datasets.services.cell_service` |
| `backend.services.rerun_service` | `backend.datasets.services.rerun_service` |
| `backend.services.converter_service` | `backend.converter.service` |
| `backend.routers.*` | `backend.datasets.routers.*` or `backend.converter.router` |

---

### Task 1: Create core/ with config and storage abstraction

**Files:**
- Create: `backend/core/__init__.py`
- Create: `backend/core/config.py`
- Create: `backend/core/storage/__init__.py`
- Create: `backend/core/storage/base.py`
- Create: `backend/core/storage/local.py`
- Modify: `backend/config.py` (convert to re-export shim)

- [ ] **Step 1: Create backend/core/ directory structure and config**

Create `backend/core/__init__.py` (empty), copy `backend/config.py` to `backend/core/config.py` (content identical).

- [ ] **Step 2: Create storage abstraction — base.py**

```python
# backend/core/storage/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator


@dataclass
class FileStat:
    path: str
    size: int
    is_dir: bool
    modified: float


class StorageBackend(ABC):
    """Abstract interface for filesystem-like storage backends."""

    @abstractmethod
    async def list(self, prefix: str) -> list[FileStat]: ...

    @abstractmethod
    async def read_bytes(self, path: str) -> bytes: ...

    @abstractmethod
    async def write_bytes(self, path: str, data: bytes) -> None: ...

    @abstractmethod
    async def exists(self, path: str) -> bool: ...

    @abstractmethod
    async def stat(self, path: str) -> FileStat: ...

    @abstractmethod
    async def delete(self, path: str) -> None: ...
```

- [ ] **Step 3: Create storage abstraction — local.py**

```python
# backend/core/storage/local.py
from __future__ import annotations
import asyncio
from pathlib import Path
from .base import FileStat, StorageBackend


class LocalStorage(StorageBackend):
    """Storage backend for local/NAS filesystem access."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, path: str) -> Path:
        resolved = (self._root / path).resolve()
        if not resolved.is_relative_to(self._root):
            raise ValueError(f"Path escapes storage root: {path}")
        return resolved

    async def list(self, prefix: str = "") -> list[FileStat]:
        target = self._resolve(prefix)
        if not target.is_dir():
            return []

        def _scan():
            return [
                FileStat(
                    path=str(child.relative_to(self._root)),
                    size=child.stat().st_size if child.is_file() else 0,
                    is_dir=child.is_dir(),
                    modified=child.stat().st_mtime,
                )
                for child in sorted(target.iterdir())
            ]
        return await asyncio.to_thread(_scan)

    async def read_bytes(self, path: str) -> bytes:
        resolved = self._resolve(path)
        return await asyncio.to_thread(resolved.read_bytes)

    async def write_bytes(self, path: str, data: bytes) -> None:
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(resolved.write_bytes, data)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._resolve(path).exists)

    async def stat(self, path: str) -> FileStat:
        resolved = self._resolve(path)
        st = await asyncio.to_thread(resolved.stat)
        return FileStat(
            path=path,
            size=st.st_size,
            is_dir=resolved.is_dir(),
            modified=st.st_mtime,
        )

    async def delete(self, path: str) -> None:
        resolved = self._resolve(path)
        if resolved.is_dir():
            import shutil
            await asyncio.to_thread(shutil.rmtree, resolved)
        else:
            await asyncio.to_thread(resolved.unlink)
```

- [ ] **Step 4: Create storage __init__.py**

```python
# backend/core/storage/__init__.py
from .base import FileStat, StorageBackend
from .local import LocalStorage

__all__ = ["FileStat", "LocalStorage", "StorageBackend"]
```

- [ ] **Step 5: Convert old backend/config.py to re-export shim**

```python
# backend/config.py — backwards-compatibility shim
from backend.core.config import Settings, settings  # noqa: F401
```

- [ ] **Step 6: Verify — import test**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -c "from backend.core.config import settings; print(settings.fastapi_port)"`
Expected: `8001`

Run: `python -c "from backend.config import settings; print(settings.fastapi_port)"`
Expected: `8001` (shim works)

Run: `python -c "from backend.core.storage import StorageBackend, LocalStorage; print('OK')"`
Expected: `OK`

---

### Task 2: Create datasets/ domain — schemas

**Files:**
- Create: `backend/datasets/__init__.py`
- Create: `backend/datasets/schemas.py`
- Modify: `backend/models/schemas.py` (convert to re-export shim)

- [ ] **Step 1: Create backend/datasets/__init__.py** (empty)

- [ ] **Step 2: Copy backend/models/schemas.py → backend/datasets/schemas.py**

Content is identical — schemas.py has no backend imports.

- [ ] **Step 3: Convert old backend/models/schemas.py to re-export shim**

```python
# backend/models/schemas.py — backwards-compatibility shim
from backend.datasets.schemas import *  # noqa: F401, F403
from backend.datasets.schemas import (  # explicit re-exports for type checkers
    BulkGradeRequest,
    CellInfo,
    DatasetExportRequest,
    DatasetInfo,
    DatasetLoadRequest,
    DatasetSummary,
    DistributionBin,
    DistributionRequest,
    DistributionResponse,
    Episode,
    EpisodeColumnAdd,
    EpisodeUpdate,
    FieldInfo,
    InfoFieldUpdate,
    Task,
    TaskUpdate,
)
```

- [ ] **Step 4: Verify**

Run: `python -c "from backend.datasets.schemas import Episode; print(Episode.__name__)"`
Expected: `Episode`

Run: `python -c "from backend.models.schemas import Episode; print(Episode.__name__)"`
Expected: `Episode` (shim works)

---

### Task 3: Create datasets/ domain — services

**Files:**
- Create: `backend/datasets/services/__init__.py`
- Create: 9 service files under `backend/datasets/services/`
- Modify: 9 files under `backend/services/` (convert to re-export shims)

Each new service file is a copy of the original with imports updated per the remapping table:
- `backend.config` → `backend.core.config`
- `backend.models.schemas` → `backend.datasets.schemas`
- `backend.services.X` → `backend.datasets.services.X`

- [ ] **Step 1: Create backend/datasets/services/__init__.py** (empty)

- [ ] **Step 2: Create all 9 dataset service files with updated imports**

Files to create (each is a copy of original with updated import paths):
1. `backend/datasets/services/dataset_service.py`
2. `backend/datasets/services/episode_service.py`
3. `backend/datasets/services/task_service.py`
4. `backend/datasets/services/export_service.py`
5. `backend/datasets/services/distribution_service.py`
6. `backend/datasets/services/fields_service.py`
7. `backend/datasets/services/dataset_ops_service.py`
8. `backend/datasets/services/cell_service.py`
9. `backend/datasets/services/rerun_service.py`

Import changes per file:
- `dataset_service.py`: `backend.config` → `backend.core.config`
- `episode_service.py`: `backend.config` → `backend.core.config`, `backend.models.schemas` → `backend.datasets.schemas`, `backend.services.dataset_service` → `backend.datasets.services.dataset_service`
- `task_service.py`: `backend.services.dataset_service` → `backend.datasets.services.dataset_service`
- `export_service.py`: `backend.services.dataset_service` → `backend.datasets.services.dataset_service`, `backend.services.episode_service` → `backend.datasets.services.episode_service`
- `distribution_service.py`: `backend.models.schemas` → `backend.datasets.schemas`, lazy `backend.services.dataset_service` → `backend.datasets.services.dataset_service`, lazy `backend.services.episode_service` → `backend.datasets.services.episode_service`
- `fields_service.py`: no backend imports to change
- `dataset_ops_service.py`: no backend imports to change
- `cell_service.py`: `backend.models.schemas` → `backend.datasets.schemas`, lazy `backend.services.episode_service` → `backend.datasets.services.episode_service`
- `rerun_service.py`: `backend.services.dataset_service` → `backend.datasets.services.dataset_service`

- [ ] **Step 3: Convert old backend/services/ files to re-export shims**

Each old file becomes a shim like:
```python
# backend/services/dataset_service.py — backwards-compatibility shim
from backend.datasets.services.dataset_service import *  # noqa: F401, F403
from backend.datasets.services.dataset_service import DatasetService, dataset_service
```

Pattern for each:
- `dataset_service.py`: re-export `DatasetService`, `dataset_service`
- `episode_service.py`: re-export `EpisodeService`, `EpisodeNotFoundError`, `episode_service`, `_load_sidecar`
- `task_service.py`: re-export `get_tasks`, `get_task`, `update_task`
- `export_service.py`: re-export `export_dataset`
- `distribution_service.py`: re-export `get_available_fields`, `compute_distribution`
- `fields_service.py`: re-export all public functions
- `dataset_ops_service.py`: re-export `DatasetOpsService`, `dataset_ops_service`
- `cell_service.py`: re-export `scan_cells`, `get_datasets_in_cell`
- `rerun_service.py`: re-export `init_rerun`, `visualize_episode`

- [ ] **Step 4: Verify**

Run: `python -c "from backend.datasets.services.dataset_service import dataset_service; print(type(dataset_service).__name__)"`
Expected: `DatasetService`

Run: `python -c "from backend.services.dataset_service import dataset_service; print(type(dataset_service).__name__)"`
Expected: `DatasetService` (shim)

---

### Task 4: Create datasets/ domain — routers

**Files:**
- Create: `backend/datasets/routers/__init__.py`
- Create: 10 router files under `backend/datasets/routers/`
- Modify: 10 files under `backend/routers/` (convert to re-export shims)

Each new router file is a copy of the original with imports updated:
- `backend.config` → `backend.core.config`
- `backend.models.schemas` → `backend.datasets.schemas`
- `backend.services.X` → `backend.datasets.services.X`

- [ ] **Step 1: Create backend/datasets/routers/__init__.py** (empty)

- [ ] **Step 2: Create all 10 dataset router files with updated imports**

Files:
1. `datasets.py`: update `backend.config`, `backend.models.schemas`, `backend.services.dataset_service`, `backend.services.export_service`
2. `episodes.py`: update `backend.models.schemas`, `backend.services.episode_service`
3. `tasks.py`: update `backend.models.schemas`, `backend.services` (task_service)
4. `videos.py`: update `backend.services.dataset_service`
5. `scalars.py`: update `backend.services.dataset_service`
6. `distribution.py`: update `backend.config`, `backend.models.schemas`, `backend.services.distribution_service`
7. `fields.py`: update `backend.config`, `backend.models.schemas`, `backend.services.fields_service`
8. `dataset_ops.py`: update `backend.services.dataset_ops_service`
9. `cells.py`: update `backend.config`, `backend.models.schemas`, `backend.services.cell_service`
10. `rerun.py`: update `backend.services` (rerun_service)

- [ ] **Step 3: Convert old backend/routers/ files to re-export shims**

Each old file: `from backend.datasets.routers.X import router  # noqa: F401`

- [ ] **Step 4: Verify**

Run: `python -c "from backend.datasets.routers.datasets import router; print(router.prefix)"`
Expected: `/api/datasets`

---

### Task 5: Create converter/ domain

**Files:**
- Create: `backend/converter/__init__.py`
- Create: `backend/converter/router.py`
- Create: `backend/converter/service.py`
- Modify: `backend/routers/converter.py` (re-export shim)
- Modify: `backend/services/converter_service.py` (re-export shim)

- [ ] **Step 1: Create backend/converter/ with router.py and service.py**

`service.py`: copy of `backend/services/converter_service.py` (no backend imports to update).
`router.py`: copy of `backend/routers/converter.py` with `backend.services` → `backend.converter.service`.

- [ ] **Step 2: Convert old files to re-export shims**

- [ ] **Step 3: Verify**

Run: `python -c "from backend.converter.router import router; print(router.prefix)"`
Expected: `/api/converter`

---

### Task 6: Update main.py

**Files:**
- Modify: `backend/main.py`

- [ ] **Step 1: Update main.py imports to new domain paths**

```python
from backend.core.config import settings
from backend.datasets.routers import (
    datasets, episodes, tasks, rerun, videos, scalars,
    dataset_ops, cells, distribution, fields,
)
from backend.converter import router as converter_router
from backend.datasets.services import rerun_service
```

And update the `app.include_router` for converter:
```python
app.include_router(converter_router.router)
```

- [ ] **Step 2: Verify — start the server**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && timeout 5 python -c "from backend.main import app; print([r.path for r in app.routes][:5])"` 
Expected: prints first 5 route paths without error

---

### Task 7: Update test imports and run full test suite

**Files:**
- Modify: all 16 test files

- [ ] **Step 1: Update test imports to use new paths**

All test files should import from new domain paths:
- `backend.config` → `backend.core.config`
- `backend.services.X` → `backend.datasets.services.X`
- `backend.main` stays as-is (main.py location unchanged)

- [ ] **Step 2: Run full test suite**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -m pytest tests/ -x --tb=short 2>&1 | tail -30`

- [ ] **Step 3: Fix any import errors**

If tests fail due to import errors, trace and fix the specific import path.

---

### Task 8: Remove old re-export shims

**Files:**
- Delete content from: 22 shim files (replace with empty or remove)

- [ ] **Step 1: Remove shim files**

After all tests pass with new imports, the shim files under `backend/services/`, `backend/routers/`, `backend/models/`, and `backend/config.py` can be replaced with minimal re-exports or removed entirely.

Decision: **Keep shims** for now — they cost nothing and prevent breakage from any external scripts or tools that import from old paths.

- [ ] **Step 2: Final verification**

Run: `python -m pytest tests/ -x --tb=short`
Run: `timeout 5 uvicorn backend.main:app --host 127.0.0.1 --port 0 2>&1 | head -5`
