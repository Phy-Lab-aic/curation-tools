# robodata-studio — Plan B: Overview Tab + Fields Tab

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Overview tab (user-selectable field distribution visualization from parquet data) and the Fields tab (add/edit custom fields in `meta/info.json` and columns in `meta/episodes/*.parquet`).

**Architecture:** Backend services use pyarrow column projection to read only selected columns for distribution aggregation. The Overview tab presents a field selector panel + chart grid with auto-recommended chart types. The Fields tab shows a split view: Dataset Info (info.json) and Episode Columns (parquet) with inline editing. Both tabs are wired into the existing DatasetPage state machine.

**Tech Stack:** FastAPI, pyarrow, pydantic, React 18, TypeScript, Vite, axios, recharts (new dep for charts)

---

## Background: Domain Concepts

- **LeRobot v3.0 dataset:** `meta/info.json` (dataset metadata) + `meta/episodes/chunk-*/file-*.parquet` (episode-level data)
- **Distribution:** Aggregate values of a selected column across all episodes → histogram (numeric) or bar chart (categorical)
- **info.json system fields:** `fps`, `total_episodes`, `robot_type`, etc. — read-only
- **info.json custom fields:** User-added fields — editable/deletable
- **Episode parquet columns:** `episode_index`, `length`, `task_index`, etc. — system columns are read-only; custom columns can be added

---

## File Map

**Created:**
- `backend/services/distribution_service.py` — pyarrow column aggregation
- `backend/services/fields_service.py` — info.json + parquet field editing
- `backend/routers/distribution.py` — `/api/datasets/distribution` endpoint
- `backend/routers/fields.py` — `/api/datasets/info-fields` + `/api/datasets/episode-columns` endpoints
- `tests/test_distribution_service.py` — distribution service tests
- `tests/test_fields_service.py` — fields service tests
- `frontend/src/components/OverviewTab.tsx` — distribution visualization UI
- `frontend/src/components/FieldsTab.tsx` — field editor UI
- `frontend/src/hooks/useDistribution.ts` — distribution data hook
- `frontend/src/hooks/useFields.ts` — fields editing hook

**Modified:**
- `backend/main.py` — register new routers
- `backend/models/schemas.py` — add distribution/fields request/response models
- `frontend/src/types/index.ts` — add distribution/fields types
- `frontend/src/App.css` — add overview/fields tab CSS
- `frontend/src/components/DatasetPage.tsx` — wire Overview + Fields tabs
- `frontend/package.json` — add `recharts` dependency

---

## Task 1: Install recharts + Add CSS for Overview/Fields Tabs

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Install recharts**

```bash
cd frontend && npm install recharts
```

- [ ] **Step 2: Append Overview + Fields CSS to `frontend/src/App.css`**

Add at the end of the file:

```css
/* ── Overview tab ─────────────────────────────── */
.overview-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.overview-fields-panel {
  width: 220px;
  flex-shrink: 0;
  background: #111;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}

.fields-panel-section {
  border-bottom: 1px solid var(--border);
}
.fields-panel-section-header {
  padding: 8px 12px;
  font-size: 9px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.fields-panel-section-header:hover { color: var(--text-muted); }

.field-checkbox {
  padding: 4px 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
}
.field-checkbox:hover { color: var(--text); background: var(--panel2); }
.field-checkbox input[type="checkbox"] { accent-color: var(--accent); }
.field-checkbox.checked { color: var(--text); }

.overview-charts {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chart-panel {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.chart-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}
.chart-panel-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text);
  font-family: monospace;
}
.chart-panel-close {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}
.chart-panel-close:hover { color: var(--text-muted); }
.chart-panel-body {
  padding: 12px;
  height: 200px;
}

.chart-type-select {
  background: var(--panel2);
  border: 1px solid var(--border2);
  border-radius: 3px;
  color: var(--text-muted);
  font-size: 10px;
  padding: 2px 4px;
  outline: none;
}
.chart-type-select:focus { border-color: var(--accent); }

/* ── Fields tab ───────────────────────────────── */
.fields-layout {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.fields-nav {
  width: 180px;
  flex-shrink: 0;
  background: #111;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}
.fields-nav-item {
  padding: 10px 14px;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
  border-left: 2px solid transparent;
  background: none;
  border-top: none;
  border-bottom: 1px solid #1a1a1a;
  border-right: none;
  text-align: left;
}
.fields-nav-item:hover { color: var(--text); background: var(--panel2); }
.fields-nav-item.active {
  color: var(--text);
  border-left-color: var(--accent);
  background: var(--accent-dim);
}

.fields-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.field-table {
  width: 100%;
  border-collapse: collapse;
}
.field-table th {
  text-align: left;
  font-size: 9px;
  color: var(--text-dim);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
}
.field-table td {
  font-size: 11px;
  color: var(--text);
  padding: 5px 10px;
  border-bottom: 1px solid #1a1a1a;
  font-family: monospace;
}
.field-table .system { color: var(--text-muted); }
.field-table .custom { color: var(--text); }

.field-delete-btn {
  background: none;
  border: none;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 11px;
  padding: 2px 4px;
}
.field-delete-btn:hover { color: var(--c-red); }

.field-add-form {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.field-add-form label {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 9px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.field-add-form input, .field-add-form select {
  background: var(--panel2);
  border: 1px solid var(--border2);
  border-radius: 4px;
  padding: 5px 8px;
  font-size: 11px;
  color: var(--text);
  outline: none;
}
.field-add-form input:focus, .field-add-form select:focus { border-color: var(--accent); }

.parquet-warning {
  background: rgba(250, 222, 42, 0.06);
  border: 1px solid rgba(250, 222, 42, 0.15);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 10px;
  color: var(--c-yellow);
  margin-bottom: 12px;
}
```

- [ ] **Step 3: Commit**

```bash
cd /home/tommoro/jm_ws/local_data_pipline/curation-tools
git add frontend/package.json frontend/package-lock.json frontend/src/App.css
git commit -m "feat: add recharts dep + Overview/Fields tab CSS"
```

---

## Task 2: Backend — Distribution Schemas

**Files:**
- Modify: `backend/models/schemas.py`

- [ ] **Step 1: Append distribution schemas to `backend/models/schemas.py`**

```python
class DistributionRequest(BaseModel):
    dataset_path: str
    field: str
    chart_type: str = "auto"  # "auto", "histogram", "bar"


class FieldInfo(BaseModel):
    name: str
    dtype: str  # "int64", "float64", "string", "bool", etc.
    is_system: bool  # True = read-only system column


class DistributionBin(BaseModel):
    label: str
    count: int


class DistributionResponse(BaseModel):
    field: str
    dtype: str
    chart_type: str  # "histogram" or "bar"
    bins: list[DistributionBin]
    total: int


class InfoFieldUpdate(BaseModel):
    key: str
    value: str | int | float | bool | None  # None = delete


class EpisodeColumnAdd(BaseModel):
    dataset_path: str
    column_name: str
    dtype: str  # "string", "int64", "float64", "bool"
    default_value: str | int | float | bool = ""
```

- [ ] **Step 2: Commit**

```bash
git add backend/models/schemas.py
git commit -m "feat: distribution and fields schemas"
```

---

## Task 3: Backend — Distribution Service + Tests

**Files:**
- Create: `backend/services/distribution_service.py`
- Create: `tests/test_distribution_service.py`

- [ ] **Step 1: Write tests in `tests/test_distribution_service.py`**

```python
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.services.distribution_service import (
    get_available_fields,
    compute_distribution,
)


@pytest.fixture
def mock_dataset(tmp_path: Path):
    """Create a fake dataset with episodes parquet + info.json."""
    # info.json
    info = {
        "fps": 30,
        "total_episodes": 6,
        "robot_type": "ur5e",
        "total_tasks": 2,
        "features": {},
    }
    meta = tmp_path / "meta"
    meta.mkdir()
    (meta / "info.json").write_text(json.dumps(info))

    # episodes parquet
    ep_dir = meta / "episodes" / "chunk-000"
    ep_dir.mkdir(parents=True)
    table = pa.table({
        "episode_index": [0, 1, 2, 3, 4, 5],
        "length": [100, 200, 150, 300, 250, 180],
        "task_index": [0, 0, 1, 1, 0, 1],
        "grade": ["good", "good", "bad", None, "normal", "good"],
        "robot_type": ["ur5e", "ur5e", "ur5e", "ur5e", "ur5e", "ur5e"],
    })
    pq.write_table(table, str(ep_dir / "file-000.parquet"))

    return tmp_path


def test_get_available_fields(mock_dataset):
    fields = get_available_fields(str(mock_dataset))
    names = {f.name for f in fields}
    assert "episode_index" in names
    assert "length" in names
    assert "grade" in names


def test_get_available_fields_returns_dtype(mock_dataset):
    fields = get_available_fields(str(mock_dataset))
    field_map = {f.name: f for f in fields}
    assert field_map["length"].dtype == "int64"
    assert field_map["grade"].dtype == "string"


def test_compute_distribution_numeric(mock_dataset):
    result = compute_distribution(str(mock_dataset), "length", chart_type="auto")
    assert result.field == "length"
    assert result.chart_type == "histogram"
    assert result.total == 6
    assert sum(b.count for b in result.bins) == 6


def test_compute_distribution_categorical(mock_dataset):
    result = compute_distribution(str(mock_dataset), "grade", chart_type="auto")
    assert result.field == "grade"
    assert result.chart_type == "bar"
    assert result.total == 6
    # good=3, bad=1, normal=1, null=1
    label_counts = {b.label: b.count for b in result.bins}
    assert label_counts["good"] == 3
    assert label_counts["bad"] == 1


def test_compute_distribution_nonexistent_field(mock_dataset):
    with pytest.raises(ValueError, match="not found"):
        compute_distribution(str(mock_dataset), "nonexistent", chart_type="auto")


def test_compute_distribution_explicit_bar(mock_dataset):
    result = compute_distribution(str(mock_dataset), "task_index", chart_type="bar")
    assert result.chart_type == "bar"
    assert all(isinstance(b.label, str) for b in result.bins)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && .venv/bin/pytest tests/test_distribution_service.py -v 2>&1 | tail -10
```

Expected: `ModuleNotFoundError` — distribution_service doesn't exist yet.

- [ ] **Step 3: Create `backend/services/distribution_service.py`**

```python
"""Service for computing column distributions from episode parquet files.

Uses pyarrow column projection to read only the selected field,
keeping memory usage low even for large datasets.
"""

from __future__ import annotations

import json
import logging
from glob import glob
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from backend.models.schemas import DistributionBin, DistributionResponse, FieldInfo

logger = logging.getLogger(__name__)

# System columns in episode parquet — always read-only
SYSTEM_COLUMNS = {
    "episode_index", "length", "task_index", "chunk_index", "file_index",
    "dataset_from_index", "dataset_to_index", "task_instruction",
}


def get_available_fields(dataset_path: str) -> list[FieldInfo]:
    """Return all columns available in episode parquet files."""
    root = Path(dataset_path)
    parquet_files = sorted(glob(str(root / "meta" / "episodes" / "chunk-*" / "file-*.parquet")))
    if not parquet_files:
        return []

    schema = pq.read_schema(parquet_files[0])
    fields: list[FieldInfo] = []
    for i in range(len(schema)):
        field = schema.field(i)
        dtype = _arrow_type_to_str(field.type)
        fields.append(FieldInfo(
            name=field.name,
            dtype=dtype,
            is_system=field.name in SYSTEM_COLUMNS,
        ))
    return fields


def compute_distribution(
    dataset_path: str,
    field: str,
    chart_type: str = "auto",
) -> DistributionResponse:
    """Compute value distribution for a single column.

    Uses column projection — only the selected field is read from parquet.
    """
    root = Path(dataset_path)
    parquet_files = sorted(glob(str(root / "meta" / "episodes" / "chunk-*" / "file-*.parquet")))
    if not parquet_files:
        raise ValueError(f"No episode parquet files found in {root}")

    # Read only the selected column
    tables: list[pa.Table] = []
    for f in parquet_files:
        schema = pq.read_schema(f)
        if field not in schema.names:
            raise ValueError(f"Field '{field}' not found in parquet schema")
        table = pq.read_table(f, columns=[field])
        tables.append(table)

    combined = pa.concat_tables(tables, promote_options="default")
    column = combined.column(field)
    total = len(column)
    dtype = _arrow_type_to_str(column.type)

    # Determine chart type
    if chart_type == "auto":
        chart_type = "histogram" if _is_numeric(column.type) else "bar"

    if chart_type == "histogram":
        bins = _histogram_bins(column)
    else:
        bins = _categorical_bins(column)

    return DistributionResponse(
        field=field,
        dtype=dtype,
        chart_type=chart_type,
        bins=bins,
        total=total,
    )


def _is_numeric(arrow_type: pa.DataType) -> bool:
    return pa.types.is_integer(arrow_type) or pa.types.is_floating(arrow_type)


def _histogram_bins(column: pa.ChunkedArray, num_bins: int = 20) -> list[DistributionBin]:
    """Create histogram bins for numeric data."""
    arr = column.to_pylist()
    valid = [v for v in arr if v is not None]
    if not valid:
        return []

    min_val = min(valid)
    max_val = max(valid)

    if min_val == max_val:
        return [DistributionBin(label=str(min_val), count=len(valid))]

    bin_width = (max_val - min_val) / num_bins
    bins: list[DistributionBin] = []
    for i in range(num_bins):
        lo = min_val + i * bin_width
        hi = lo + bin_width
        count = sum(1 for v in valid if lo <= v < hi) if i < num_bins - 1 \
            else sum(1 for v in valid if lo <= v <= hi)
        if count > 0:
            label = f"{lo:.1f}-{hi:.1f}" if isinstance(lo, float) else f"{int(lo)}-{int(hi)}"
            bins.append(DistributionBin(label=label, count=count))
    return bins


def _categorical_bins(column: pa.ChunkedArray) -> list[DistributionBin]:
    """Count occurrences of each unique value."""
    arr = column.to_pylist()
    counts: dict[str, int] = {}
    for v in arr:
        key = str(v) if v is not None else "(null)"
        counts[key] = counts.get(key, 0) + 1

    # Sort by count descending
    return [
        DistributionBin(label=k, count=v)
        for k, v in sorted(counts.items(), key=lambda x: -x[1])
    ]


def _arrow_type_to_str(t: pa.DataType) -> str:
    if pa.types.is_int64(t):
        return "int64"
    if pa.types.is_int32(t):
        return "int32"
    if pa.types.is_float64(t):
        return "float64"
    if pa.types.is_float32(t):
        return "float32"
    if pa.types.is_boolean(t):
        return "bool"
    if pa.types.is_string(t) or pa.types.is_large_string(t):
        return "string"
    return str(t)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
.venv/bin/pytest tests/test_distribution_service.py -v
```

Expected: 6/6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/distribution_service.py tests/test_distribution_service.py
git commit -m "feat: distribution service with pyarrow column projection"
```

---

## Task 4: Backend — Distribution Router

**Files:**
- Create: `backend/routers/distribution.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Create `backend/routers/distribution.py`**

```python
"""Router for dataset distribution analysis endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.models.schemas import (
    DistributionRequest,
    DistributionResponse,
    FieldInfo,
)
from backend.services.distribution_service import (
    compute_distribution,
    get_available_fields,
)

router = APIRouter(prefix="/api/datasets", tags=["distribution"])


@router.get("/fields", response_model=list[FieldInfo])
async def list_fields(dataset_path: str):
    """Return all available fields in episode parquet files."""
    resolved = Path(dataset_path).resolve()
    allowed_roots = [Path(r).resolve() for r in settings.allowed_dataset_roots]
    if not any(resolved == root or str(resolved).startswith(str(root) + "/") for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed roots")

    try:
        return get_available_fields(dataset_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/distribution", response_model=DistributionResponse)
async def get_distribution(req: DistributionRequest):
    """Compute value distribution for a selected field."""
    resolved = Path(req.dataset_path).resolve()
    allowed_roots = [Path(r).resolve() for r in settings.allowed_dataset_roots]
    if not any(resolved == root or str(resolved).startswith(str(root) + "/") for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed roots")

    try:
        return compute_distribution(req.dataset_path, req.field, req.chart_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 2: Register router in `backend/main.py`**

Read `backend/main.py`. Add to the router imports line:

```python
from backend.routers import distribution
```

And add after existing router registrations:

```python
app.include_router(distribution.router)
```

- [ ] **Step 3: Verify startup**

```bash
cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && uv run python -c "from backend.main import app; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/routers/distribution.py backend/main.py
git commit -m "feat: /api/datasets/distribution and /api/datasets/fields endpoints"
```

---

## Task 5: Backend — Fields Service + Tests

**Files:**
- Create: `backend/services/fields_service.py`
- Create: `tests/test_fields_service.py`

- [ ] **Step 1: Write tests in `tests/test_fields_service.py`**

```python
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.services.fields_service import (
    get_info_fields,
    update_info_field,
    delete_info_field,
    get_episode_columns,
    add_episode_column,
)

SYSTEM_INFO_KEYS = {"fps", "total_episodes", "total_tasks", "robot_type", "features",
                     "total_frames", "total_chunks", "chunks_size", "data_path",
                     "videos_path", "splits"}


@pytest.fixture
def mock_dataset(tmp_path: Path):
    info = {
        "fps": 30,
        "total_episodes": 3,
        "robot_type": "ur5e",
        "total_tasks": 1,
        "features": {},
        "custom_field_1": "hello",
        "custom_field_2": 42,
    }
    meta = tmp_path / "meta"
    meta.mkdir()
    (meta / "info.json").write_text(json.dumps(info))

    ep_dir = meta / "episodes" / "chunk-000"
    ep_dir.mkdir(parents=True)
    table = pa.table({
        "episode_index": [0, 1, 2],
        "length": [100, 200, 150],
        "task_index": [0, 0, 1],
    })
    pq.write_table(table, str(ep_dir / "file-000.parquet"))

    return tmp_path


def test_get_info_fields(mock_dataset):
    fields = get_info_fields(str(mock_dataset))
    keys = {f["key"] for f in fields}
    assert "fps" in keys
    assert "custom_field_1" in keys


def test_get_info_fields_marks_system(mock_dataset):
    fields = get_info_fields(str(mock_dataset))
    field_map = {f["key"]: f for f in fields}
    assert field_map["fps"]["is_system"] is True
    assert field_map["custom_field_1"]["is_system"] is False


def test_update_info_field(mock_dataset):
    update_info_field(str(mock_dataset), "custom_field_1", "updated")
    info = json.loads((mock_dataset / "meta" / "info.json").read_text())
    assert info["custom_field_1"] == "updated"


def test_update_info_field_adds_new(mock_dataset):
    update_info_field(str(mock_dataset), "new_field", "new_value")
    info = json.loads((mock_dataset / "meta" / "info.json").read_text())
    assert info["new_field"] == "new_value"


def test_update_info_field_rejects_system(mock_dataset):
    with pytest.raises(ValueError, match="system field"):
        update_info_field(str(mock_dataset), "fps", 60)


def test_delete_info_field(mock_dataset):
    delete_info_field(str(mock_dataset), "custom_field_1")
    info = json.loads((mock_dataset / "meta" / "info.json").read_text())
    assert "custom_field_1" not in info


def test_delete_info_field_rejects_system(mock_dataset):
    with pytest.raises(ValueError, match="system field"):
        delete_info_field(str(mock_dataset), "fps")


def test_get_episode_columns(mock_dataset):
    cols = get_episode_columns(str(mock_dataset))
    names = {c["name"] for c in cols}
    assert "episode_index" in names
    assert "length" in names


def test_add_episode_column(mock_dataset):
    add_episode_column(str(mock_dataset), "quality_score", "float64", 0.0)
    cols = get_episode_columns(str(mock_dataset))
    names = {c["name"] for c in cols}
    assert "quality_score" in names


def test_add_episode_column_duplicate(mock_dataset):
    with pytest.raises(ValueError, match="already exists"):
        add_episode_column(str(mock_dataset), "length", "int64", 0)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
.venv/bin/pytest tests/test_fields_service.py -v 2>&1 | tail -10
```

- [ ] **Step 3: Create `backend/services/fields_service.py`**

```python
"""Service for managing dataset fields (info.json + episode parquet columns).

info.json system fields are read-only. Custom fields can be added, edited, deleted.
Adding a parquet column requires rewriting all parquet files in the dataset.
"""

from __future__ import annotations

import json
import logging
from glob import glob
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

# Keys in info.json that are system-managed
SYSTEM_INFO_KEYS = {
    "fps", "total_episodes", "total_tasks", "robot_type", "features",
    "total_frames", "total_chunks", "chunks_size", "data_path",
    "videos_path", "splits",
}

# Columns in episode parquet that are system-managed
SYSTEM_EPISODE_COLUMNS = {
    "episode_index", "length", "task_index", "chunk_index", "file_index",
    "dataset_from_index", "dataset_to_index", "task_instruction",
}

DTYPE_MAP = {
    "string": pa.string(),
    "int64": pa.int64(),
    "float64": pa.float64(),
    "bool": pa.bool_(),
}


def get_info_fields(dataset_path: str) -> list[dict]:
    """Return all fields from info.json with system/custom classification."""
    info = _read_info(dataset_path)
    fields = []
    for key, value in info.items():
        fields.append({
            "key": key,
            "value": value,
            "dtype": type(value).__name__,
            "is_system": key in SYSTEM_INFO_KEYS,
        })
    return fields


def update_info_field(dataset_path: str, key: str, value: str | int | float | bool) -> None:
    """Update or add a custom field in info.json. System fields are rejected."""
    if key in SYSTEM_INFO_KEYS:
        raise ValueError(f"Cannot modify system field: {key}")

    info = _read_info(dataset_path)
    info[key] = value
    _write_info(dataset_path, info)


def delete_info_field(dataset_path: str, key: str) -> None:
    """Delete a custom field from info.json. System fields are rejected."""
    if key in SYSTEM_INFO_KEYS:
        raise ValueError(f"Cannot delete system field: {key}")

    info = _read_info(dataset_path)
    info.pop(key, None)
    _write_info(dataset_path, info)


def get_episode_columns(dataset_path: str) -> list[dict]:
    """Return all columns from episode parquet with system/custom classification."""
    root = Path(dataset_path)
    parquet_files = sorted(glob(str(root / "meta" / "episodes" / "chunk-*" / "file-*.parquet")))
    if not parquet_files:
        return []

    schema = pq.read_schema(parquet_files[0])
    columns = []
    for i in range(len(schema)):
        field = schema.field(i)
        columns.append({
            "name": field.name,
            "dtype": str(field.type),
            "is_system": field.name in SYSTEM_EPISODE_COLUMNS,
        })
    return columns


def add_episode_column(
    dataset_path: str,
    column_name: str,
    dtype: str,
    default_value: str | int | float | bool,
) -> None:
    """Add a new column to all episode parquet files.

    WARNING: This rewrites every parquet file in the dataset.
    """
    root = Path(dataset_path)
    parquet_files = sorted(glob(str(root / "meta" / "episodes" / "chunk-*" / "file-*.parquet")))
    if not parquet_files:
        raise ValueError("No episode parquet files found")

    # Check column doesn't already exist
    schema = pq.read_schema(parquet_files[0])
    if column_name in schema.names:
        raise ValueError(f"Column '{column_name}' already exists")

    arrow_type = DTYPE_MAP.get(dtype)
    if arrow_type is None:
        raise ValueError(f"Unsupported dtype: {dtype}. Use: {', '.join(DTYPE_MAP.keys())}")

    for f in parquet_files:
        file_path = Path(f)
        table = pq.read_table(str(file_path))
        num_rows = table.num_rows

        # Create the new column filled with default value
        new_col = pa.array([default_value] * num_rows, type=arrow_type)
        table = table.append_column(column_name, new_col)

        pq.write_table(table, str(file_path))
        logger.info("Added column '%s' to %s (%d rows)", column_name, file_path, num_rows)


def _read_info(dataset_path: str) -> dict:
    info_path = Path(dataset_path) / "meta" / "info.json"
    content = info_path.read_text(encoding="utf-8").rstrip("\x00")
    return json.loads(content)


def _write_info(dataset_path: str, info: dict) -> None:
    info_path = Path(dataset_path) / "meta" / "info.json"
    info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
.venv/bin/pytest tests/test_fields_service.py -v
```

Expected: 11/11 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/fields_service.py tests/test_fields_service.py
git commit -m "feat: fields service for info.json + parquet column editing"
```

---

## Task 6: Backend — Fields Router

**Files:**
- Create: `backend/routers/fields.py`
- Modify: `backend/main.py`

- [ ] **Step 1: Create `backend/routers/fields.py`**

```python
"""Router for dataset field management endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.models.schemas import EpisodeColumnAdd, InfoFieldUpdate
from backend.services.fields_service import (
    add_episode_column,
    delete_info_field,
    get_episode_columns,
    get_info_fields,
    update_info_field,
)

router = APIRouter(prefix="/api/datasets", tags=["fields"])


def _validate_path(dataset_path: str) -> None:
    resolved = Path(dataset_path).resolve()
    allowed_roots = [Path(r).resolve() for r in settings.allowed_dataset_roots]
    if not any(resolved == root or str(resolved).startswith(str(root) + "/") for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed roots")


@router.get("/info-fields")
async def list_info_fields(dataset_path: str):
    """Return all fields from info.json."""
    _validate_path(dataset_path)
    try:
        return get_info_fields(dataset_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset not found")


@router.patch("/info-fields")
async def update_info(dataset_path: str, req: InfoFieldUpdate):
    """Add or update a custom field in info.json."""
    _validate_path(dataset_path)
    try:
        if req.value is None:
            delete_info_field(dataset_path, req.key)
        else:
            update_info_field(dataset_path, req.key, req.value)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/episode-columns")
async def list_episode_columns(dataset_path: str):
    """Return all columns from episode parquet files."""
    _validate_path(dataset_path)
    return get_episode_columns(dataset_path)


@router.post("/episode-columns")
async def add_column(req: EpisodeColumnAdd):
    """Add a new column to all episode parquet files."""
    _validate_path(req.dataset_path)
    try:
        add_episode_column(req.dataset_path, req.column_name, req.dtype, req.default_value)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 2: Register router in `backend/main.py`**

Add import:
```python
from backend.routers import fields
```

And registration:
```python
app.include_router(fields.router)
```

- [ ] **Step 3: Verify startup**

```bash
uv run python -c "from backend.main import app; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add backend/routers/fields.py backend/main.py
git commit -m "feat: /api/datasets/info-fields and /api/datasets/episode-columns endpoints"
```

---

## Task 7: Frontend — Types + useDistribution + useFields Hooks

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/hooks/useDistribution.ts`
- Create: `frontend/src/hooks/useFields.ts`

- [ ] **Step 1: Add distribution/fields types to `frontend/src/types/index.ts`**

Append at the end:

```typescript
// ── Distribution types ──────────────────────────

export interface FieldInfo {
  name: string
  dtype: string
  is_system: boolean
}

export interface DistributionBin {
  label: string
  count: number
}

export interface DistributionResult {
  field: string
  dtype: string
  chart_type: 'histogram' | 'bar'
  bins: DistributionBin[]
  total: number
}

// ── Fields tab types ────────────────────────────

export interface InfoField {
  key: string
  value: unknown
  dtype: string
  is_system: boolean
}

export interface EpisodeColumn {
  name: string
  dtype: string
  is_system: boolean
}
```

- [ ] **Step 2: Create `frontend/src/hooks/useDistribution.ts`**

```typescript
import { useState, useCallback } from 'react'
import client from '../api/client'
import type { FieldInfo, DistributionResult } from '../types'

interface UseDistributionReturn {
  fields: FieldInfo[]
  charts: DistributionResult[]
  loading: boolean
  error: string | null
  fetchFields: (datasetPath: string) => Promise<void>
  addChart: (datasetPath: string, field: string, chartType?: string) => Promise<void>
  removeChart: (field: string) => void
}

export function useDistribution(): UseDistributionReturn {
  const [fields, setFields] = useState<FieldInfo[]>([])
  const [charts, setCharts] = useState<DistributionResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchFields = useCallback(async (datasetPath: string) => {
    setLoading(true)
    setError(null)
    try {
      const resp = await client.get<FieldInfo[]>('/datasets/fields', {
        params: { dataset_path: datasetPath },
      })
      setFields(resp.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch fields')
    } finally {
      setLoading(false)
    }
  }, [])

  const addChart = useCallback(async (datasetPath: string, field: string, chartType = 'auto') => {
    setLoading(true)
    setError(null)
    try {
      const resp = await client.post<DistributionResult>('/datasets/distribution', {
        dataset_path: datasetPath,
        field,
        chart_type: chartType,
      })
      setCharts(prev => {
        const filtered = prev.filter(c => c.field !== field)
        return [...filtered, resp.data]
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to compute distribution')
    } finally {
      setLoading(false)
    }
  }, [])

  const removeChart = useCallback((field: string) => {
    setCharts(prev => prev.filter(c => c.field !== field))
  }, [])

  return { fields, charts, loading, error, fetchFields, addChart, removeChart }
}
```

- [ ] **Step 3: Create `frontend/src/hooks/useFields.ts`**

```typescript
import { useState, useCallback } from 'react'
import client from '../api/client'
import type { InfoField, EpisodeColumn } from '../types'

interface UseFieldsReturn {
  infoFields: InfoField[]
  episodeColumns: EpisodeColumn[]
  loading: boolean
  error: string | null
  fetchInfoFields: (datasetPath: string) => Promise<void>
  fetchEpisodeColumns: (datasetPath: string) => Promise<void>
  updateInfoField: (datasetPath: string, key: string, value: unknown) => Promise<void>
  deleteInfoField: (datasetPath: string, key: string) => Promise<void>
  addEpisodeColumn: (datasetPath: string, name: string, dtype: string, defaultValue: unknown) => Promise<void>
}

export function useFields(): UseFieldsReturn {
  const [infoFields, setInfoFields] = useState<InfoField[]>([])
  const [episodeColumns, setEpisodeColumns] = useState<EpisodeColumn[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchInfoFields = useCallback(async (datasetPath: string) => {
    setLoading(true)
    setError(null)
    try {
      const resp = await client.get<InfoField[]>('/datasets/info-fields', {
        params: { dataset_path: datasetPath },
      })
      setInfoFields(resp.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch info fields')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchEpisodeColumns = useCallback(async (datasetPath: string) => {
    setLoading(true)
    setError(null)
    try {
      const resp = await client.get<EpisodeColumn[]>('/datasets/episode-columns', {
        params: { dataset_path: datasetPath },
      })
      setEpisodeColumns(resp.data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch episode columns')
    } finally {
      setLoading(false)
    }
  }, [])

  const updateInfoField = useCallback(async (datasetPath: string, key: string, value: unknown) => {
    try {
      await client.patch('/datasets/info-fields', { key, value }, {
        params: { dataset_path: datasetPath },
      })
      await fetchInfoFields(datasetPath)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update field')
    }
  }, [fetchInfoFields])

  const deleteInfoField = useCallback(async (datasetPath: string, key: string) => {
    try {
      await client.patch('/datasets/info-fields', { key, value: null }, {
        params: { dataset_path: datasetPath },
      })
      await fetchInfoFields(datasetPath)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete field')
    }
  }, [fetchInfoFields])

  const addEpisodeColumn = useCallback(async (
    datasetPath: string, name: string, dtype: string, defaultValue: unknown,
  ) => {
    setLoading(true)
    try {
      await client.post('/datasets/episode-columns', {
        dataset_path: datasetPath,
        column_name: name,
        dtype,
        default_value: defaultValue,
      })
      await fetchEpisodeColumns(datasetPath)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add column')
    } finally {
      setLoading(false)
    }
  }, [fetchEpisodeColumns])

  return {
    infoFields, episodeColumns, loading, error,
    fetchInfoFields, fetchEpisodeColumns, updateInfoField, deleteInfoField, addEpisodeColumn,
  }
}
```

- [ ] **Step 4: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
cd /home/tommoro/jm_ws/local_data_pipline/curation-tools
git add frontend/src/types/index.ts frontend/src/hooks/useDistribution.ts frontend/src/hooks/useFields.ts
git commit -m "feat: distribution and fields types + hooks"
```

---

## Task 8: Frontend — OverviewTab Component

**Files:**
- Create: `frontend/src/components/OverviewTab.tsx`

- [ ] **Step 1: Create `frontend/src/components/OverviewTab.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useDistribution } from '../hooks/useDistribution'
import type { DistributionResult } from '../types'

interface OverviewTabProps {
  datasetPath: string
}

const CHART_COLORS = ['#5794f2', '#73bf69', '#fade2a', '#f08080', '#b877d9', '#ff9830']

export function OverviewTab({ datasetPath }: OverviewTabProps) {
  const { fields, charts, loading, error, fetchFields, addChart, removeChart } = useDistribution()
  const [selectedFields, setSelectedFields] = useState<Set<string>>(new Set())

  useEffect(() => {
    void fetchFields(datasetPath)
  }, [datasetPath, fetchFields])

  const toggleField = (fieldName: string) => {
    setSelectedFields(prev => {
      const next = new Set(prev)
      if (next.has(fieldName)) {
        next.delete(fieldName)
        removeChart(fieldName)
      } else {
        next.add(fieldName)
        void addChart(datasetPath, fieldName)
      }
      return next
    })
  }

  // Group fields by system vs custom
  const systemFields = fields.filter(f => f.is_system)
  const customFields = fields.filter(f => !f.is_system)

  return (
    <div className="overview-layout">
      {/* Left: field selector */}
      <div className="overview-fields-panel">
        <FieldSection title="System columns" fields={systemFields} selected={selectedFields} onToggle={toggleField} />
        <FieldSection title="Custom columns" fields={customFields} selected={selectedFields} onToggle={toggleField} />
      </div>

      {/* Right: chart grid */}
      <div className="overview-charts">
        {/* Stats bar */}
        <div className="stats-bar">
          <div className="stat-card">
            <div className="stat-card-n">{charts.length > 0 ? charts[0].total : '—'}</div>
            <div className="stat-card-l">Episodes</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-n">{charts.length}</div>
            <div className="stat-card-l">Charts</div>
          </div>
          <div className="stat-card">
            <div className="stat-card-n">{fields.length}</div>
            <div className="stat-card-l">Fields</div>
          </div>
        </div>

        {loading && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Computing...</div>}
        {error && <div style={{ fontSize: 11, color: 'var(--c-red)' }}>{error}</div>}

        {charts.map((chart, idx) => (
          <ChartPanel
            key={chart.field}
            chart={chart}
            color={CHART_COLORS[idx % CHART_COLORS.length]}
            onRemove={() => {
              removeChart(chart.field)
              setSelectedFields(prev => {
                const next = new Set(prev)
                next.delete(chart.field)
                return next
              })
            }}
            onChangeType={(newType) => void addChart(datasetPath, chart.field, newType)}
          />
        ))}

        {charts.length === 0 && !loading && (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
            Select fields from the left panel to visualize distributions
          </div>
        )}
      </div>
    </div>
  )
}

function FieldSection({
  title, fields, selected, onToggle,
}: {
  title: string
  fields: { name: string; dtype: string }[]
  selected: Set<string>
  onToggle: (name: string) => void
}) {
  if (fields.length === 0) return null
  return (
    <div className="fields-panel-section">
      <div className="fields-panel-section-header">
        <span>{title}</span>
        <span style={{ color: 'var(--text-dim)', fontSize: 9 }}>{fields.length}</span>
      </div>
      {fields.map(f => (
        <label key={f.name} className={`field-checkbox${selected.has(f.name) ? ' checked' : ''}`}>
          <input type="checkbox" checked={selected.has(f.name)} onChange={() => onToggle(f.name)} />
          <span>{f.name}</span>
          <span style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--text-dim)' }}>{f.dtype}</span>
        </label>
      ))}
    </div>
  )
}

function ChartPanel({
  chart, color, onRemove, onChangeType,
}: {
  chart: DistributionResult
  color: string
  onRemove: () => void
  onChangeType: (type: string) => void
}) {
  return (
    <div className="chart-panel">
      <div className="chart-panel-header">
        <span className="chart-panel-title">{chart.field}</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <select
            className="chart-type-select"
            value={chart.chart_type}
            onChange={e => onChangeType(e.target.value)}
          >
            <option value="histogram">Histogram</option>
            <option value="bar">Bar</option>
          </select>
          <span style={{ fontSize: 9, color: 'var(--text-dim)' }}>n={chart.total}</span>
          <button className="chart-panel-close" onClick={onRemove}>×</button>
        </div>
      </div>
      <div className="chart-panel-body">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart.bins} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
            <XAxis
              dataKey="label"
              tick={{ fontSize: 9, fill: '#555' }}
              axisLine={{ stroke: '#222' }}
              tickLine={false}
            />
            <YAxis
              tick={{ fontSize: 9, fill: '#555' }}
              axisLine={false}
              tickLine={false}
              width={30}
            />
            <Tooltip
              contentStyle={{
                background: '#161616',
                border: '1px solid #2a2a2a',
                borderRadius: 4,
                fontSize: 11,
                color: '#d9d9d9',
              }}
            />
            <Bar dataKey="count" fill={color} radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep OverviewTab
```

- [ ] **Step 3: Commit**

```bash
cd /home/tommoro/jm_ws/local_data_pipline/curation-tools
git add frontend/src/components/OverviewTab.tsx
git commit -m "feat: OverviewTab — field distribution visualization"
```

---

## Task 9: Frontend — FieldsTab Component

**Files:**
- Create: `frontend/src/components/FieldsTab.tsx`

- [ ] **Step 1: Create `frontend/src/components/FieldsTab.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useFields } from '../hooks/useFields'

interface FieldsTabProps {
  datasetPath: string
}

type FieldsSection = 'info' | 'columns'

export function FieldsTab({ datasetPath }: FieldsTabProps) {
  const {
    infoFields, episodeColumns, loading, error,
    fetchInfoFields, fetchEpisodeColumns,
    updateInfoField, deleteInfoField, addEpisodeColumn,
  } = useFields()
  const [section, setSection] = useState<FieldsSection>('info')

  useEffect(() => {
    void fetchInfoFields(datasetPath)
    void fetchEpisodeColumns(datasetPath)
  }, [datasetPath, fetchInfoFields, fetchEpisodeColumns])

  return (
    <div className="fields-layout">
      {/* Left nav */}
      <div className="fields-nav">
        <button
          className={`fields-nav-item${section === 'info' ? ' active' : ''}`}
          onClick={() => setSection('info')}
        >
          Dataset Info
        </button>
        <button
          className={`fields-nav-item${section === 'columns' ? ' active' : ''}`}
          onClick={() => setSection('columns')}
        >
          Episode Columns
        </button>
      </div>

      {/* Content */}
      <div className="fields-content">
        {loading && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Loading...</div>}
        {error && <div style={{ fontSize: 11, color: 'var(--c-red)' }}>{error}</div>}

        {section === 'info' && (
          <InfoFieldsPanel
            fields={infoFields}
            datasetPath={datasetPath}
            onUpdate={updateInfoField}
            onDelete={deleteInfoField}
          />
        )}
        {section === 'columns' && (
          <EpisodeColumnsPanel
            columns={episodeColumns}
            datasetPath={datasetPath}
            onAddColumn={addEpisodeColumn}
          />
        )}
      </div>
    </div>
  )
}

function InfoFieldsPanel({
  fields, datasetPath, onUpdate, onDelete,
}: {
  fields: { key: string; value: unknown; dtype: string; is_system: boolean }[]
  datasetPath: string
  onUpdate: (path: string, key: string, value: unknown) => Promise<void>
  onDelete: (path: string, key: string) => Promise<void>
}) {
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')
  const [newType, setNewType] = useState('string')

  const handleAdd = () => {
    if (!newKey.trim()) return
    let val: unknown = newValue
    if (newType === 'number') val = Number(newValue)
    if (newType === 'boolean') val = newValue === 'true'
    void onUpdate(datasetPath, newKey.trim(), val)
    setNewKey('')
    setNewValue('')
  }

  const systemFields = fields.filter(f => f.is_system)
  const customFields = fields.filter(f => !f.is_system)

  return (
    <div>
      <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
        System fields
      </div>
      <table className="field-table">
        <thead>
          <tr><th>Key</th><th>Value</th><th>Type</th></tr>
        </thead>
        <tbody>
          {systemFields.map(f => (
            <tr key={f.key}>
              <td className="system">{f.key}</td>
              <td className="system">{JSON.stringify(f.value)}</td>
              <td className="system">{f.dtype}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div style={{ fontSize: 10, color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.06em', margin: '16px 0 8px' }}>
        Custom fields
      </div>
      <table className="field-table">
        <thead>
          <tr><th>Key</th><th>Value</th><th>Type</th><th></th></tr>
        </thead>
        <tbody>
          {customFields.map(f => (
            <tr key={f.key}>
              <td className="custom">{f.key}</td>
              <td className="custom">{JSON.stringify(f.value)}</td>
              <td className="custom">{f.dtype}</td>
              <td>
                <button className="field-delete-btn" onClick={() => void onDelete(datasetPath, f.key)}>×</button>
              </td>
            </tr>
          ))}
          {customFields.length === 0 && (
            <tr><td colSpan={4} style={{ color: 'var(--text-muted)' }}>No custom fields</td></tr>
          )}
        </tbody>
      </table>

      <div className="field-add-form">
        <label>
          Key
          <input value={newKey} onChange={e => setNewKey(e.target.value)} placeholder="field_name" />
        </label>
        <label>
          Type
          <select value={newType} onChange={e => setNewType(e.target.value)}>
            <option value="string">string</option>
            <option value="number">number</option>
            <option value="boolean">boolean</option>
          </select>
        </label>
        <label>
          Default
          <input value={newValue} onChange={e => setNewValue(e.target.value)} placeholder="value" />
        </label>
        <button className="btn-primary" onClick={handleAdd} disabled={!newKey.trim()}>Add</button>
      </div>
    </div>
  )
}

function EpisodeColumnsPanel({
  columns, datasetPath, onAddColumn,
}: {
  columns: { name: string; dtype: string; is_system: boolean }[]
  datasetPath: string
  onAddColumn: (path: string, name: string, dtype: string, defaultValue: unknown) => Promise<void>
}) {
  const [newName, setNewName] = useState('')
  const [newDtype, setNewDtype] = useState('string')
  const [newDefault, setNewDefault] = useState('')

  const handleAdd = () => {
    if (!newName.trim()) return
    let val: unknown = newDefault
    if (newDtype === 'int64') val = Number(newDefault) || 0
    if (newDtype === 'float64') val = Number(newDefault) || 0.0
    if (newDtype === 'bool') val = newDefault === 'true'
    void onAddColumn(datasetPath, newName.trim(), newDtype, val)
    setNewName('')
    setNewDefault('')
  }

  return (
    <div>
      <div className="parquet-warning">
        Adding a column rewrites all episode parquet files. This may take time for large datasets.
      </div>

      <table className="field-table">
        <thead>
          <tr><th>Column</th><th>Type</th><th>Kind</th></tr>
        </thead>
        <tbody>
          {columns.map(c => (
            <tr key={c.name}>
              <td className={c.is_system ? 'system' : 'custom'}>{c.name}</td>
              <td className={c.is_system ? 'system' : 'custom'}>{c.dtype}</td>
              <td className={c.is_system ? 'system' : 'custom'}>
                {c.is_system ? 'system' : 'custom'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="field-add-form">
        <label>
          Column name
          <input value={newName} onChange={e => setNewName(e.target.value)} placeholder="column_name" />
        </label>
        <label>
          Type
          <select value={newDtype} onChange={e => setNewDtype(e.target.value)}>
            <option value="string">string</option>
            <option value="int64">int64</option>
            <option value="float64">float64</option>
            <option value="bool">bool</option>
          </select>
        </label>
        <label>
          Default
          <input value={newDefault} onChange={e => setNewDefault(e.target.value)} placeholder="default" />
        </label>
        <button className="btn-primary" onClick={handleAdd} disabled={!newName.trim()}>Add Column</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep FieldsTab
```

- [ ] **Step 3: Commit**

```bash
cd /home/tommoro/jm_ws/local_data_pipline/curation-tools
git add frontend/src/components/FieldsTab.tsx
git commit -m "feat: FieldsTab — info.json + parquet column editor"
```

---

## Task 10: Wire Overview + Fields Tabs into DatasetPage

**Files:**
- Modify: `frontend/src/components/DatasetPage.tsx`

- [ ] **Step 1: Read the current `DatasetPage.tsx`**

Read the file to confirm the structure.

- [ ] **Step 2: Replace the placeholder branch with real tab components**

In `DatasetPage.tsx`, find the block:

```tsx
if (tab !== 'curate' && tab !== 'ops') {
    return (
      <div style={{ padding: 20, color: 'var(--text-muted)', fontSize: 12 }}>
        {tab === 'overview' && 'Overview tab — coming in Plan B'}
        {tab === 'fields' && 'Fields tab — coming in Plan B'}
      </div>
    )
  }
```

Replace it with:

```tsx
  if (tab === 'overview') {
    return (
      <div className="dataset-page">
        <OverviewTab datasetPath={datasetPath} />
      </div>
    )
  }

  if (tab === 'fields') {
    return (
      <div className="dataset-page">
        <FieldsTab datasetPath={datasetPath} />
      </div>
    )
  }
```

Also add the imports at the top:

```tsx
import { OverviewTab } from './OverviewTab'
import { FieldsTab } from './FieldsTab'
```

- [ ] **Step 3: TypeScript check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```

Expected: zero errors.

- [ ] **Step 4: Run backend tests**

```bash
cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && .venv/bin/pytest tests/test_cell_service.py tests/test_distribution_service.py tests/test_fields_service.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
cd /home/tommoro/jm_ws/local_data_pipline/curation-tools
git add frontend/src/components/DatasetPage.tsx
git commit -m "feat: wire OverviewTab and FieldsTab into DatasetPage"
```

---

## Completion Check

- [ ] **Run all backend tests**

```bash
.venv/bin/pytest tests/test_cell_service.py tests/test_distribution_service.py tests/test_fields_service.py -v
```

Expected: all tests pass (7 + 6 + 11 = 24 tests).

- [ ] **Run frontend type check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Manual smoke test**

1. Backend starts: `uv run python -m backend.main`
2. Frontend starts: `cd frontend && npm run dev`
3. Navigate to a dataset → Overview tab
4. Select fields from left panel → charts appear
5. Change chart type dropdown → chart re-renders
6. Remove chart with × button
7. Navigate to Fields tab
8. See system fields (read-only) and custom fields
9. Add a custom field to info.json
10. Navigate to Episode Columns
11. See parquet columns listed
12. Add a new column → warning shown → column added

---

*This completes the robodata-studio redesign. Plan A covered Foundation + Navigation + Curate. Plan B covers Overview (distribution) + Fields (editing).*
