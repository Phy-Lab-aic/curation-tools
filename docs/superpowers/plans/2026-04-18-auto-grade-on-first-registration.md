# Auto-grade ungraded episodes on first dataset registration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** At the first time a dataset is seen by curation-tools, automatically set `grade='normal'` + a machine-written reason on ungraded episodes whose `action[N]` vs `observation.state[N]` divergence contains a severe band. Idempotent, never overwrites user grades.

**Architecture:** New module `backend/datasets/services/auto_grade_service.py` owns the pass. DB schema v3 adds `datasets.auto_graded_at` and backfills existing rows. `episode_service` calls `ensure_auto_graded` right after `_ensure_migrated`. Thresholds and run-downgrade logic mirror `frontend/src/components/ScalarChart.tsx` (`0.15` / `0.30` / `MIN_SEVERE_RUN=5`).

**Tech Stack:** Python 3.11+, FastAPI, aiosqlite, pyarrow. Tests via pytest (already present).

**Spec:** `docs/superpowers/specs/2026-04-18-auto-grade-on-first-registration-design.md`.

---

## File Structure

- **Create:** `backend/datasets/services/auto_grade_service.py` — band computation (port of frontend), `ensure_auto_graded` orchestration.
- **Modify:** `backend/core/db.py` — add `SCHEMA_V3` (column + backfill), bump `PRAGMA user_version`.
- **Modify:** `backend/datasets/services/episode_service.py` — call `ensure_auto_graded` in `get_episodes` and `get_episode` after migration.
- **Create:** `tests/test_auto_grade_bands.py` — unit tests for band math (pure function).
- **Create:** `tests/test_auto_grade_service.py` — integration test that exercises the ensure pass against a fixture DB + minimal fixture parquet.

---

### Task 1: DB migration — add `auto_graded_at` column

**Files:**
- Modify: `backend/core/db.py`

- [ ] **Step 1: Append SCHEMA_V3 and bump version in `init_db`**

In `backend/core/db.py`, just below the existing `SCHEMA_V2` block, add:

```python
SCHEMA_V3 = """
ALTER TABLE datasets ADD COLUMN auto_graded_at TEXT;
UPDATE datasets SET auto_graded_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE auto_graded_at IS NULL;
"""
```

Extend `init_db` with a third migration branch. Replace the body of `init_db` after the v2 block:

```python
    if version < 3:
        await db.executescript(SCHEMA_V3)
        await db.execute("PRAGMA user_version = 3")
        await db.commit()
        logger.info("Database upgraded to v3 (auto_graded_at column) at %s", _get_db_path())
```

Place this new branch directly after the `if version < 2:` block.

- [ ] **Step 2: Run existing db tests**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -m pytest tests/ -k "db or schema or migration" -x -q`
Expected: all existing tests still pass. If no dedicated DB test exists, run the full suite quickly: `python -m pytest -x -q -k "not slow"` (or equivalent repo convention — confirm before committing).

- [ ] **Step 3: Commit**

```bash
git add backend/core/db.py
git commit -m "feat(backend): add datasets.auto_graded_at column (schema v3)

Stamped to now() for existing rows so the upcoming auto-grade pass
only fires on datasets seen for the first time after this migration."
```

---

### Task 2: Band computation in Python (pure)

Extract the math so it has unit tests without touching parquet, DB, or network.

**Files:**
- Create: `backend/datasets/services/auto_grade_service.py`
- Create: `tests/test_auto_grade_bands.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_auto_grade_bands.py`:

```python
from backend.datasets.services.auto_grade_service import (
    compute_bands,
    unify_key,
    MIN_SEVERE_RUN,
)


def test_empty_inputs_return_no_bands():
    assert compute_bands([], []) == []
    assert compute_bands([1.0], []) == []


def test_constant_series_returns_no_bands():
    obs = [0.5] * 20
    act = [0.5] * 20
    assert compute_bands(obs, act) == []


def test_pure_noise_under_threshold_returns_no_bands():
    obs = [i * 0.01 for i in range(100)]
    act = [i * 0.01 + 0.001 for i in range(100)]
    assert compute_bands(obs, act) == []


def test_short_severe_run_is_demoted_to_moderate():
    # range = 1.0, 3-frame severe at 40% (below MIN_SEVERE_RUN)
    obs = [0.0] * 10
    act = [0.0, 0.0, 0.4, 0.4, 0.4, 0.0, 0.0, 0.0, 0.0, 1.0]
    bands = compute_bands(obs, act)
    severe_runs = [b for b in bands if b["level"] == "severe"]
    moderate_runs = [b for b in bands if b["level"] == "moderate"]
    assert severe_runs == []
    assert any(r["start"] == 2 and r["end"] == 4 for r in moderate_runs)


def test_long_severe_run_stays_severe():
    # range = 1.0, 6-frame severe at 40%
    obs = [0.0] * 15
    act = [0.0, 0.0, 0.4, 0.4, 0.4, 0.4, 0.4, 0.4, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    bands = compute_bands(obs, act)
    severe_runs = [b for b in bands if b["level"] == "severe"]
    assert len(severe_runs) == 1
    run = severe_runs[0]
    assert run["start"] == 2 and run["end"] == 7
    assert (run["end"] - run["start"] + 1) >= MIN_SEVERE_RUN


def test_uneven_lengths_use_min():
    obs = [0.0] * 5
    act = [0.0] * 3
    # Range over the min-length region is 0, so no bands
    assert compute_bands(obs, act) == []


def test_unify_key_index_form():
    assert unify_key("observation.state[0]") == "[0]"
    assert unify_key("action[12]") == "[12]"


def test_unify_key_dotted_form():
    assert unify_key("observation.state.joint1") == "joint1"
    assert unify_key("action.joint1") == "joint1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -m pytest tests/test_auto_grade_bands.py -v`
Expected: All tests fail with `ModuleNotFoundError` or `ImportError` on the service module.

- [ ] **Step 3: Write the pure band computation**

Create `backend/datasets/services/auto_grade_service.py`:

```python
"""Auto-grade service — runs once per dataset on first registration.

Detects severe divergence between paired observation.state[N] and action[N]
scalar columns and writes `grade='normal'` + a machine-written reason on
ungraded episodes. Idempotency guard is `datasets.auto_graded_at`.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterable, TypedDict

import pyarrow.parquet as pq

from backend.core.db import get_db

logger = logging.getLogger(__name__)


# Tuned against labelled good/normal/bad episodes — see spec for evidence.
MODERATE_RATIO = 0.15
SEVERE_RATIO = 0.30
MIN_SEVERE_RUN = 5


class Band(TypedDict):
    start: int
    end: int
    level: str  # 'moderate' | 'severe'


_IDX_RE = re.compile(r"\[(\d+)\]$")


def unify_key(key: str) -> str:
    """Reduce a scalar key to its pair-matching identifier.

    observation.state[0] <-> action[0]      -> '[0]'
    observation.state.joint1 <-> action.joint1 -> 'joint1'
    """
    m = _IDX_RE.search(key)
    if m:
        return m.group(0)
    return (
        key.replace("observation.state.", "")
        .replace("observation.state", "")
        .replace("observation.", "")
        .replace("action.", "")
        .replace("action", "")
    )


def _classify(ratio: float) -> str | None:
    if ratio > SEVERE_RATIO:
        return "severe"
    if ratio > MODERATE_RATIO:
        return "moderate"
    return None


def _range_of(series: list[float]) -> float:
    if not series:
        return 0.0
    lo = hi = series[0]
    for v in series[1:]:
        if v < lo:
            lo = v
        if v > hi:
            hi = v
    return hi - lo


def compute_bands(obs: list[float], act: list[float]) -> list[Band]:
    """Pairwise divergence bands for one joint. Returns merged runs."""
    n = min(len(obs), len(act))
    if n == 0:
        return []
    rng = max(_range_of(obs[:n]), _range_of(act[:n]))
    if rng == 0:
        return []

    # Per-frame level
    levels: list[str | None] = []
    for i in range(n):
        r = abs(act[i] - obs[i]) / rng
        levels.append(_classify(r))

    # Merge runs
    bands: list[Band] = []
    cur: str | None = None
    start = 0
    for i, lv in enumerate(levels):
        if lv != cur:
            if cur is not None:
                bands.append({"start": start, "end": i - 1, "level": cur})
            cur = lv
            start = i
    if cur is not None:
        bands.append({"start": start, "end": n - 1, "level": cur})

    # Downgrade short severe runs to moderate (gripper transients are NOT
    # data-quality problems; only sustained tracking error is).
    for b in bands:
        if b["level"] == "severe" and (b["end"] - b["start"] + 1) < MIN_SEVERE_RUN:
            b["level"] = "moderate"

    # Re-merge adjacent same-level runs after downgrade
    merged: list[Band] = []
    for b in bands:
        if merged and merged[-1]["level"] == b["level"] and merged[-1]["end"] + 1 == b["start"]:
            merged[-1] = {"start": merged[-1]["start"], "end": b["end"], "level": b["level"]}
        else:
            merged.append(dict(b))  # type: ignore[arg-type]
    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -m pytest tests/test_auto_grade_bands.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/services/auto_grade_service.py tests/test_auto_grade_bands.py
git commit -m "feat(backend): port divergence-band math from ScalarChart.tsx to Python

Pure helper + unit tests. Orchestration layer (episode iteration,
DB writes, idempotency) comes in the next commit."
```

---

### Task 3: Orchestration — `ensure_auto_graded`

Extend the service with the dataset-wide pass. Keep it in the same file; the whole feature is small.

**Files:**
- Modify: `backend/datasets/services/auto_grade_service.py`

- [ ] **Step 1: Add episode iteration + severity collection**

Append to `backend/datasets/services/auto_grade_service.py` (below `compute_bands`):

```python
# ---------------------------------------------------------------------------
# Per-episode severity summary
# ---------------------------------------------------------------------------


class JointSeverity(TypedDict):
    joint: str
    severe_ratio: float  # severe_frames / episode_length


def _episode_severity(
    observations: dict[str, list[float]],
    actions: dict[str, list[float]],
) -> list[JointSeverity]:
    """Return per-joint severe-frame ratios for joints with any severe band."""
    # Pair by unified key
    act_by_name: dict[str, list[float]] = {}
    for k, v in actions.items():
        act_by_name[unify_key(k)] = v

    out: list[JointSeverity] = []
    for k, obs in observations.items():
        name = unify_key(k)
        act = act_by_name.get(name)
        if act is None:
            continue
        bands = compute_bands(obs, act)
        severe_frames = 0
        for b in bands:
            if b["level"] == "severe":
                severe_frames += b["end"] - b["start"] + 1
        if severe_frames > 0:
            n = min(len(obs), len(act))
            if n > 0:
                out.append({"joint": name, "severe_ratio": severe_frames / n})
    # Sort descending by severe_ratio for stable reason string
    out.sort(key=lambda x: x["severe_ratio"], reverse=True)
    return out


def _format_reason(sev: list[JointSeverity], top: int = 3) -> str:
    """'[auto] severe divergence: [13] 33.3%, [5] 19.6%, [7] 6.4%'"""
    parts = [f"{s['joint']} {s['severe_ratio'] * 100:.1f}%" for s in sev[:top]]
    return "[auto] severe divergence: " + ", ".join(parts)
```

- [ ] **Step 2: Add the orchestration entry point**

Append:

```python
# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def _load_scalars_for_episode(
    dataset_path: Path,
    episode_row: dict,
    features: dict,
) -> tuple[dict[str, list[float]], dict[str, list[float]]] | None:
    """Return (observations, actions) dicts for one episode, or None on error.

    Mirrors `backend/datasets/routers/scalars.py` but skipped terminal-frame
    bookkeeping and filters to scalar (non-image, non-video) columns only.
    """
    import asyncio
    import numpy as np

    from_idx = episode_row["dataset_from_index"]
    to_idx = episode_row["dataset_to_index"]
    chunk_idx = episode_row["data/chunk_index"]
    file_idx = episode_row["data/file_index"]
    data_path = dataset_path / f"data/chunk-{chunk_idx:03d}/file-{file_idx:03d}.parquet"
    if not data_path.exists():
        return None

    try:
        schema = await asyncio.to_thread(pq.read_schema, data_path)
    except Exception as exc:
        logger.warning("auto_grade: schema read failed for %s: %s", data_path, exc)
        return None
    all_columns = set(schema.names)

    state_columns: list[str] = []
    action_columns: list[str] = []
    for col, feature in features.items():
        dtype = feature.get("dtype", "")
        if dtype in ("image", "video"):
            continue
        if col.startswith("observation.") and col in all_columns:
            state_columns.append(col)
        elif col.startswith("action") and col in all_columns:
            action_columns.append(col)
    needed_columns = state_columns + action_columns
    if not needed_columns:
        return {}, {}

    try:
        table = await asyncio.to_thread(pq.read_table, data_path, columns=needed_columns)
    except Exception as exc:
        logger.warning("auto_grade: data read failed for %s: %s", data_path, exc)
        return None
    table = table.slice(from_idx, to_idx - from_idx)
    df = table.to_pydict()

    def _extract(columns: list[str]) -> dict[str, list[float]]:
        result: dict[str, list[float]] = {}
        for col in columns:
            values = df.get(col, [])
            scalar_series: list[float] = []
            for v in values:
                arr = np.asarray(v, dtype=float).ravel()
                if arr.size == 1:
                    scalar_series.append(float(arr[0]))
                elif arr.size > 1:
                    for dim in range(arr.size):
                        key = f"{col}[{dim}]"
                        result.setdefault(key, []).append(float(arr[dim]))
                    continue
            if scalar_series:
                result[col] = scalar_series
        return result

    return _extract(state_columns), _extract(action_columns)


async def ensure_auto_graded(dataset_id: int, dataset_path: Path) -> None:
    """Run the auto-grade pass once per dataset. Safe to call repeatedly.

    Does nothing if `datasets.auto_graded_at` is already set. Writes
    `grade='normal'` + a machine reason on every ungraded episode with at
    least one severe divergence band, then stamps `auto_graded_at` with now().
    """
    db = await get_db()
    async with db.execute(
        "SELECT auto_graded_at FROM datasets WHERE id = ?",
        (dataset_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return
    if row[0] is not None:
        return

    # Pull episode rows from the dataset's meta/episodes parquet files via the
    # existing dataset_service helpers to avoid duplicating iteration logic.
    from backend.datasets.services.dataset_service import dataset_service

    features = dataset_service.get_features()
    if not features:
        logger.info("auto_grade: no features loaded; skipping for dataset_id=%s", dataset_id)
        # Do NOT stamp — retry on next load when dataset is fully loaded.
        return

    # Collect ungraded episodes from DB so we only consider grade=NULL ones.
    async with db.execute(
        "SELECT episode_index FROM episode_annotations WHERE dataset_id = ? AND grade IS NOT NULL",
        (dataset_id,),
    ) as cursor:
        graded_rows = await cursor.fetchall()
    already_graded: set[int] = {r[0] for r in graded_rows}

    # Iterate every episode parquet row once.
    import asyncio

    auto_updates: list[tuple[int, str]] = []  # (episode_index, reason)
    for file_path in dataset_service.iter_episode_parquet_files():
        try:
            ep_table = await asyncio.to_thread(pq.read_table, file_path)
        except Exception as exc:
            logger.warning("auto_grade: episode parquet read failed for %s: %s", file_path, exc)
            # Abort without stamping so we retry on next load.
            return
        rows = ep_table.to_pylist()
        for row in rows:
            ep_idx = row.get("episode_index")
            if ep_idx is None or ep_idx in already_graded:
                continue
            scalars = await _load_scalars_for_episode(dataset_path, row, features)
            if scalars is None:
                # Read error already logged. Skip this episode but keep going.
                continue
            observations, actions = scalars
            if not observations or not actions:
                continue
            sev = _episode_severity(observations, actions)
            if not sev:
                continue
            auto_updates.append((ep_idx, _format_reason(sev)))

    # Write annotations (idempotent UPSERTs) and stamp auto_graded_at
    for ep_idx, reason in auto_updates:
        await db.execute(
            """INSERT INTO episode_annotations
                   (dataset_id, episode_index, grade, tags, reason, updated_at)
               VALUES (?, ?, 'normal', '[]', ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
               ON CONFLICT(dataset_id, episode_index) DO UPDATE SET
                   grade = CASE WHEN episode_annotations.grade IS NULL
                                THEN excluded.grade
                                ELSE episode_annotations.grade END,
                   reason = CASE WHEN episode_annotations.grade IS NULL
                                 THEN excluded.reason
                                 ELSE episode_annotations.reason END,
                   updated_at = excluded.updated_at""",
            (dataset_id, ep_idx, reason),
        )
    await db.execute(
        "UPDATE datasets SET auto_graded_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
        (dataset_id,),
    )
    await db.commit()

    if auto_updates:
        logger.info(
            "auto_grade: dataset_id=%s marked %d episodes as normal",
            dataset_id,
            len(auto_updates),
        )
    else:
        logger.info(
            "auto_grade: dataset_id=%s no severe episodes detected; stamped auto_graded_at",
            dataset_id,
        )

    # Refresh stats + invalidate dist caches so the UI reflects changes immediately.
    try:
        from backend.datasets.services.episode_service import _refresh_dataset_stats
        await _refresh_dataset_stats(dataset_id)
    except Exception as exc:
        logger.warning("auto_grade: stats refresh failed: %s", exc)
    dataset_service.distribution_cache.pop("grade:auto", None)
    dataset_service.distribution_cache.pop("grade:bar", None)
```

- [ ] **Step 3: Type-check and smoke-run module import**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -c "from backend.datasets.services.auto_grade_service import ensure_auto_graded, compute_bands; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/datasets/services/auto_grade_service.py
git commit -m "feat(backend): add ensure_auto_graded orchestration

Iterates every episode once, pairs obs/act scalars, and writes
grade='normal' + machine reason on ungraded episodes with severe
divergence. Stamped datasets.auto_graded_at guarantees one-shot
behavior per dataset."
```

---

### Task 4: Wire into `EpisodeService`

**Files:**
- Modify: `backend/datasets/services/episode_service.py`

- [ ] **Step 1: Import and call `ensure_auto_graded`**

In `backend/datasets/services/episode_service.py`:

- Add near the other service imports near the top:

```python
from backend.datasets.services.auto_grade_service import ensure_auto_graded
```

- In `EpisodeService.get_episodes`, after the existing `await _ensure_migrated(dataset_id, dataset_service.dataset_path)` line, add:

```python
        await ensure_auto_graded(dataset_id, dataset_service.dataset_path)
        annotations = await _load_annotations_from_db(dataset_id)  # reload after auto-grade
```

Replace the existing `annotations = await _load_annotations_from_db(dataset_id)` line that immediately follows `_ensure_migrated` with the reload above (it's the same call; the auto-grade pass needs to happen between them).

- Do the same in `EpisodeService.get_episode`: after `_ensure_migrated`, add the `await ensure_auto_graded(...)` before `annotations = await _load_annotations_from_db(...)`.

- [ ] **Step 2: Smoke-run the backend**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -c "import backend.main; print('import ok')"`
Expected: `import ok` with no import errors.

- [ ] **Step 3: Run existing episode/service tests**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -m pytest tests/ -x -q -k "episode or grade or annotation"`
Expected: all pre-existing tests pass. If any fail due to the new call's side effects on test fixtures (e.g. tests that don't expect `auto_graded_at` writes), adjust fixtures to stamp `auto_graded_at='pre-test'` on setup so auto-grade no-ops in those tests. Do NOT weaken the production path.

- [ ] **Step 4: Commit**

```bash
git add backend/datasets/services/episode_service.py
git commit -m "feat(backend): hook ensure_auto_graded into EpisodeService

Auto-grade pass runs once per dataset at first registration, right
after migration and before annotations are read for the response."
```

---

### Task 5: Integration test

**Files:**
- Create: `tests/test_auto_grade_service.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_auto_grade_service.py`:

```python
"""Integration test for ensure_auto_graded.

Uses an in-memory SQLite + a monkeypatched `dataset_service` that yields
fixture episode rows directly. The pure-function path (scalars → bands →
reason) is already tested in test_auto_grade_bands.py; this test focuses
on DB idempotency and ungraded-only behavior.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core import db as db_module
from backend.datasets.services import auto_grade_service


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def test_db(tmp_path: Path, monkeypatch):
    db_module._reset()
    monkeypatch.setattr(db_module, "_db_path_override", str(tmp_path / "t.db"))
    await db_module.init_db()
    conn = await db_module.get_db()
    yield conn
    await db_module.close_db()
    db_module._reset()


async def _insert_dataset(conn, path: str) -> int:
    await conn.execute(
        "INSERT INTO datasets (path, name, auto_graded_at) VALUES (?, ?, NULL)",
        (path, "t"),
    )
    await conn.commit()
    async with conn.execute("SELECT id FROM datasets WHERE path = ?", (path,)) as cur:
        row = await cur.fetchone()
    return row[0]


async def test_ensure_auto_graded_skips_if_stamped(test_db, tmp_path, monkeypatch):
    ds_id = await _insert_dataset(test_db, str(tmp_path / "ds1"))
    await test_db.execute(
        "UPDATE datasets SET auto_graded_at = '2026-04-18T00:00:00Z' WHERE id = ?",
        (ds_id,),
    )
    await test_db.commit()

    # If this raises (e.g. touches features / parquet), the idempotency guard failed.
    await auto_grade_service.ensure_auto_graded(ds_id, tmp_path / "ds1")


async def test_ensure_auto_graded_stamps_even_when_nothing_to_grade(test_db, tmp_path, monkeypatch):
    ds_id = await _insert_dataset(test_db, str(tmp_path / "ds2"))

    class _StubService:
        distribution_cache: dict = {}
        def get_features(self):
            return {}  # falsy triggers early return without stamping
        def iter_episode_parquet_files(self):
            return iter([])

    # Falsy features should cause early-return WITHOUT stamping (retry later).
    monkeypatch.setattr(auto_grade_service, "dataset_service", _StubService(), raising=False)
    await auto_grade_service.ensure_auto_graded(ds_id, tmp_path / "ds2")

    async with test_db.execute(
        "SELECT auto_graded_at FROM datasets WHERE id = ?", (ds_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] is None


async def test_ensure_auto_graded_preserves_existing_grades(test_db, tmp_path, monkeypatch):
    ds_id = await _insert_dataset(test_db, str(tmp_path / "ds3"))
    # Pre-existing grade — must not be touched.
    await test_db.execute(
        """INSERT INTO episode_annotations
               (dataset_id, episode_index, grade, tags, reason)
           VALUES (?, 0, 'good', '[]', 'user chose good')""",
        (ds_id,),
    )
    await test_db.commit()

    # Stub dataset_service with features present but zero episodes; this
    # exercises the happy path without real parquet.
    class _StubService:
        distribution_cache: dict = {}
        def get_features(self):
            return {"observation.state": {"dtype": "float32"}}
        def iter_episode_parquet_files(self):
            return iter([])

    monkeypatch.setattr(auto_grade_service, "dataset_service", _StubService(), raising=False)
    await auto_grade_service.ensure_auto_graded(ds_id, tmp_path / "ds3")

    async with test_db.execute(
        "SELECT grade, reason FROM episode_annotations WHERE dataset_id = ? AND episode_index = 0",
        (ds_id,),
    ) as cur:
        row = await cur.fetchone()
    assert row["grade"] == "good"
    assert row["reason"] == "user chose good"

    async with test_db.execute(
        "SELECT auto_graded_at FROM datasets WHERE id = ?", (ds_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] is not None  # stamped after a successful (empty) pass
```

- [ ] **Step 2: Run the test**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -m pytest tests/test_auto_grade_service.py -v`
Expected: all 3 tests PASS. If the test file fails to import due to pytest-asyncio not being configured with that exact marker style, switch to the configured style (check `pyproject.toml` / `pytest.ini` for `asyncio_mode`). Do not commit until green.

- [ ] **Step 3: Run the full backend test suite as a regression check**

Run: `cd /home/tommoro/jm_ws/local_data_pipline/curation-tools && python -m pytest -x -q`
Expected: green. If something broke, fix it — do not comment out or skip tests to force green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_auto_grade_service.py
git commit -m "test(backend): cover auto-grade idempotency and grade-preservation paths"
```

---

## Self-Review

- **Spec coverage.** Trigger point (Task 4), idempotency via `auto_graded_at` (Task 1 + Task 3 stamp), ungraded-only (Task 3 CONFLICT clause + pre-filter + Task 5 test), reason format (Task 3 `_format_reason`, Task 2 joint ordering), thresholds match frontend (Task 2 constants), DB concurrency (single-connection aiosqlite + INSERT ... ON CONFLICT), cache invalidation (Task 3 step 2 end).
- **Placeholder scan.** None.
- **Type consistency.** `Band` and `JointSeverity` TypedDicts shared. `compute_bands` return shape used consistently in `_episode_severity`. DB schema additions referenced identically in Task 1 and Task 3.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-18-auto-grade-on-first-registration.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks.

**2. Inline Execution** — batch with checkpoints.
