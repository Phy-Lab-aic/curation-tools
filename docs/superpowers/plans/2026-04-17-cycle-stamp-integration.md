# Cycle Stamp Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-app "Cycles" operation to `TrimPanel` that stamps `is_terminal` and `is_last` onto the active dataset's parquet files, using the same async job pattern as split/merge/delete, so operators no longer need to run the external `lerobot_dataset_helper/update_dataset_flags.py` script.

**Architecture:** Port the gripper-state-machine cycle detector into a new `cycle_stamp_service` (pure algorithm + atomic per-file parquet rewrite). Expose it through `DatasetOpsService.stamp_cycles()` (reusing the shared job registry) and two new endpoints on `dataset_ops` router (`POST /api/datasets/stamp-cycles` + `GET /api/datasets/stamp-cycles/status`). Add a fourth tab `CyclesTab` to `TrimPanel` that describes current stamp state, asks for explicit confirmation when overwriting, and streams status via the existing `useJobPoller` hook.

**Tech Stack:** Python 3.13 / FastAPI / pyarrow / numpy / pytest (backend). React / TypeScript / axios (frontend).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/datasets/services/cycle_stamp_service.py` | **Create** | Pure cycle detection + in-place parquet rewrite. No job-tracking here. |
| `tests/test_cycle_stamp_service.py` | **Create** | Unit tests for cycle detection + parquet rewrite (synthetic fixtures). |
| `backend/datasets/services/dataset_ops_service.py` | **Modify** | Add `stamp_cycles()` method that queues a job and runs `_run_stamp_cycles()` in executor. |
| `backend/datasets/routers/dataset_ops.py` | **Modify** | Add `StampCyclesRequest` schema, `POST /stamp-cycles`, `GET /stamp-cycles/status`. |
| `tests/test_dataset_ops_router.py` | **Modify** | Add `TestStampCycles` suite covering 202/404/already-stamped/status. |
| `frontend/src/components/TrimPanel.tsx` | **Modify** | Add `'cycles'` tab id + `<CyclesTab>` component (status fetch, confirm modal, submit+poll). |

---

### Task 1: Pure cycle-boundary detector

**Files:**
- Create: `backend/datasets/services/cycle_stamp_service.py`
- Test: `tests/test_cycle_stamp_service.py`

This isolates the gripper state machine from any filesystem concerns so we can test it with synthetic arrays and port-verify against the reference script on real data later.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cycle_stamp_service.py`:

```python
"""Tests for cycle_stamp_service — synthetic fixtures only."""

from __future__ import annotations

import numpy as np
import pytest

from backend.datasets.services.cycle_stamp_service import (
    LEFT_GRIPPER_IDX,
    RIGHT_GRIPPER_IDX,
    detect_cycle_ends,
)


def _state_with_gripper(n: int, left_trace: list[float], right_trace: list[float]) -> np.ndarray:
    """Build a (n, 16) observation.state array with the given gripper traces."""
    assert len(left_trace) == n and len(right_trace) == n
    arr = np.zeros((n, 16), dtype=np.float32)
    arr[:, LEFT_GRIPPER_IDX] = left_trace
    arr[:, RIGHT_GRIPPER_IDX] = right_trace
    return arr


class TestDetectCycleEnds:
    def test_two_cycles_on_left_gripper_only(self):
        # Open(1.0) -> Closed(0.3) -> Open(1.0) -> Closed(0.3) -> Open(1.0)
        # Each open-after-closed transition is a cycle end.
        left = [1.0, 1.0, 0.3, 0.3, 1.0, 1.0, 0.3, 0.3, 1.0, 1.0]
        right = [1.0] * 10  # always open — contributes no cycles
        states = _state_with_gripper(10, left, right)
        ends = detect_cycle_ends(states)
        # Cycle ends at indices 4 and 8 (first frames >0.8 after a <0.5 run).
        assert ends == [4, 8]

    def test_starts_closed_counts_first_open_as_cycle_end(self):
        left = [0.3, 0.3, 1.0, 1.0, 0.3, 1.0]
        right = [1.0] * 6
        states = _state_with_gripper(6, left, right)
        ends = detect_cycle_ends(states)
        assert ends == [2, 5]

    def test_both_arms_contribute(self):
        # Left cycles at frame 2; right cycles at frame 4.
        left = [1.0, 0.3, 1.0, 1.0, 1.0, 1.0]
        right = [1.0, 1.0, 1.0, 0.3, 1.0, 1.0]
        states = _state_with_gripper(6, left, right)
        ends = sorted(detect_cycle_ends(states))
        assert ends == [2, 4]

    def test_no_cycles_when_always_open(self):
        states = _state_with_gripper(20, [1.0] * 20, [1.0] * 20)
        assert detect_cycle_ends(states) == []

    def test_no_cycles_when_always_closed(self):
        states = _state_with_gripper(20, [0.3] * 20, [0.3] * 20)
        assert detect_cycle_ends(states) == []

    def test_borderline_values_ignored(self):
        # Values in the hysteresis band (0.5 <= v <= 0.8) should not trigger
        # either transition.
        left = [1.0, 0.6, 0.7, 0.6, 1.0]
        right = [1.0] * 5
        states = _state_with_gripper(5, left, right)
        assert detect_cycle_ends(states) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cycle_stamp_service.py::TestDetectCycleEnds -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.datasets.services.cycle_stamp_service'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/datasets/services/cycle_stamp_service.py`:

```python
"""Cycle-boundary detection and stamping for lerobot datasets.

Ports the gripper state machine from lerobot_dataset_helper/update_dataset_flags.py
into a pure function plus a filesystem wrapper that rewrites parquet data files
in place (atomic per file via tmp + os.replace).
"""

from __future__ import annotations

import numpy as np

# Constants mirror the reference script. Change only if a new robot type needs
# different gripper channels or thresholds.
LEFT_GRIPPER_IDX = 7
RIGHT_GRIPPER_IDX = 15
CLOSED_THRESHOLD = 0.5
OPEN_THRESHOLD = 0.8


def detect_cycle_ends(states: np.ndarray) -> list[int]:
    """Return frame indices where a gripper open-after-closed transition completes.

    Runs one state machine per gripper arm over a single episode's
    ``observation.state`` rows and merges both result sets.

    Args:
        states: (n_frames, state_dim) float array for a single episode.

    Returns:
        Sorted list of 0-based frame indices within the episode marking cycle ends.
    """
    ends: list[int] = []
    for gripper_idx in (LEFT_GRIPPER_IDX, RIGHT_GRIPPER_IDX):
        values = states[:, gripper_idx]
        # state 0 = searching for close, 1 = searching for open.
        # If the arm starts below the closed threshold, we're already looking
        # for an open transition.
        state = 1 if values[0] < CLOSED_THRESHOLD else 0
        for i in range(1, len(values)):
            v = values[i]
            if state == 0 and v < CLOSED_THRESHOLD:
                state = 1
            elif state == 1 and v > OPEN_THRESHOLD:
                ends.append(i)
                state = 0
    ends.sort()
    return ends
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cycle_stamp_service.py::TestDetectCycleEnds -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/services/cycle_stamp_service.py tests/test_cycle_stamp_service.py
git commit -m "feat(cycle-stamp): add pure gripper-cycle-end detector"
```

---

### Task 2: Dataset-level stamp pipeline (parquet IO)

**Files:**
- Modify: `backend/datasets/services/cycle_stamp_service.py`
- Test: `tests/test_cycle_stamp_service.py`

Wraps `detect_cycle_ends` into a function that walks every `data/chunk-*/file-*.parquet`, runs the detector per episode, and rewrites each file atomically with `is_terminal` and `is_last` columns added.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cycle_stamp_service.py`:

```python
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from backend.datasets.services.cycle_stamp_service import (
    describe_stamp_state,
    stamp_dataset_cycles,
)


def _write_fake_dataset(root: Path, episodes: list[dict]) -> None:
    """Build a minimal lerobot-v3-shaped dataset under ``root`` for testing.

    Each item in ``episodes`` is a dict with ``left_trace``, ``right_trace``, and
    ``length`` — lengths must match. Frames are split across two parquet files to
    ensure multi-file concat paths are exercised.
    """
    (root / "meta").mkdir(parents=True)
    (root / "meta" / "info.json").write_text(json.dumps({
        "codebase_version": "v3.0",
        "fps": 30,
        "total_episodes": len(episodes),
        "total_frames": sum(e["length"] for e in episodes),
        "features": {
            "observation.state": {"dtype": "float32", "shape": [16]},
        },
    }))

    state_rows: list[list[float]] = []
    ep_idx: list[int] = []
    frame_idx: list[int] = []
    for i, ep in enumerate(episodes):
        for f in range(ep["length"]):
            row = [0.0] * 16
            row[LEFT_GRIPPER_IDX] = ep["left_trace"][f]
            row[RIGHT_GRIPPER_IDX] = ep["right_trace"][f]
            state_rows.append(row)
            ep_idx.append(i)
            frame_idx.append(f)

    table = pa.table({
        "observation.state": pa.array(state_rows, type=pa.list_(pa.float32(), 16)),
        "episode_index": pa.array(ep_idx, type=pa.int64()),
        "frame_index": pa.array(frame_idx, type=pa.int64()),
    })
    data_dir = root / "data" / "chunk-000"
    data_dir.mkdir(parents=True)
    # Split into two files to make sure the writer concatenates correctly.
    midpoint = table.num_rows // 2
    pq.write_table(table.slice(0, midpoint), data_dir / "file-000.parquet")
    pq.write_table(table.slice(midpoint), data_dir / "file-001.parquet")


class TestStampDatasetCycles:
    def test_adds_is_terminal_and_is_last(self, tmp_path):
        ds = tmp_path / "ds"
        _write_fake_dataset(ds, [
            # ep 0: one cycle ending at frame 4
            {"length": 6,
             "left_trace": [1.0, 0.3, 0.3, 1.0, 1.0, 1.0],
             "right_trace": [1.0] * 6},
            # ep 1: no cycles (always open)
            {"length": 4,
             "left_trace": [1.0] * 4,
             "right_trace": [1.0] * 4},
        ])

        report = stamp_dataset_cycles(ds, overwrite=False)

        assert report["episodes_processed"] == 2
        assert report["is_terminal_count"] == 1
        assert report["is_last_count"] == 2

        # Verify on-disk schema and values.
        pfs = sorted((ds / "data" / "chunk-000").glob("file-*.parquet"))
        combined = pa.concat_tables([pq.read_table(p) for p in pfs])
        assert "is_terminal" in combined.schema.names
        assert "is_last" in combined.schema.names
        is_terminal = combined.column("is_terminal").to_pylist()
        is_last = combined.column("is_last").to_pylist()
        assert sum(is_terminal) == 1
        assert sum(is_last) == 2
        # ep0 is_last is row 5, ep1 is_last is row 9.
        assert is_last[5] is True
        assert is_last[9] is True

    def test_refuses_to_restamp_without_overwrite(self, tmp_path):
        ds = tmp_path / "ds"
        _write_fake_dataset(ds, [
            {"length": 4, "left_trace": [1.0] * 4, "right_trace": [1.0] * 4},
        ])
        stamp_dataset_cycles(ds, overwrite=False)

        with pytest.raises(ValueError, match="already_stamped"):
            stamp_dataset_cycles(ds, overwrite=False)

    def test_overwrite_replaces_existing_columns(self, tmp_path):
        ds = tmp_path / "ds"
        _write_fake_dataset(ds, [
            {"length": 6,
             "left_trace": [1.0, 0.3, 1.0, 1.0, 1.0, 1.0],
             "right_trace": [1.0] * 6},
        ])
        stamp_dataset_cycles(ds, overwrite=False)
        # Second run with overwrite=True should succeed and produce the same
        # (deterministic) column values.
        report = stamp_dataset_cycles(ds, overwrite=True)
        assert report["is_terminal_count"] == 1

    def test_describe_stamp_state(self, tmp_path):
        ds = tmp_path / "ds"
        _write_fake_dataset(ds, [
            {"length": 6,
             "left_trace": [1.0, 0.3, 1.0, 1.0, 1.0, 1.0],
             "right_trace": [1.0] * 6},
        ])
        before = describe_stamp_state(ds)
        assert before == {"stamped": False, "is_terminal_count_sample": 0}

        stamp_dataset_cycles(ds, overwrite=False)
        after = describe_stamp_state(ds)
        assert after["stamped"] is True
        assert after["is_terminal_count_sample"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cycle_stamp_service.py::TestStampDatasetCycles -v`
Expected: FAIL — `describe_stamp_state` and `stamp_dataset_cycles` do not exist yet.

- [ ] **Step 3: Write minimal implementation**

Append to `backend/datasets/services/cycle_stamp_service.py`:

```python
import logging
import os
from glob import glob
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)

_TERMINAL_COL = "is_terminal"
_LAST_COL = "is_last"


def _data_parquet_files(dataset_root: Path) -> list[Path]:
    """Return data parquet files in deterministic chunk/file order."""
    pattern = str(dataset_root / "data" / "chunk-*" / "file-*.parquet")
    return [Path(p) for p in sorted(glob(pattern))]


def describe_stamp_state(dataset_path: Path | str) -> dict:
    """Report whether a dataset already carries cycle-stamp columns.

    Returns ``{"stamped": bool, "is_terminal_count_sample": int}`` — the sample
    count comes from the first parquet only so this stays cheap for the UI.
    """
    root = Path(dataset_path)
    files = _data_parquet_files(root)
    if not files:
        return {"stamped": False, "is_terminal_count_sample": 0}

    schema = pq.read_schema(files[0])
    stamped = _TERMINAL_COL in schema.names
    if not stamped:
        return {"stamped": False, "is_terminal_count_sample": 0}

    sample = pq.read_table(files[0], columns=[_TERMINAL_COL]).column(_TERMINAL_COL).to_pylist()
    return {"stamped": True, "is_terminal_count_sample": int(sum(1 for v in sample if v))}


def stamp_dataset_cycles(dataset_path: Path | str, *, overwrite: bool) -> dict:
    """Detect cycle ends via gripper state machine and rewrite every data parquet.

    Each file is re-written atomically: data goes to ``<file>.tmp`` then
    ``os.replace`` swaps it into place. If any file fails we stop early — files
    processed before the failure keep their updated columns. Callers should
    treat a mid-run failure as "partial" and inspect ``describe_stamp_state``.

    Args:
        dataset_path: Root of a lerobot v3 dataset (sibling of ``meta/`` and ``data/``).
        overwrite: When False (default usage), raise ValueError('already_stamped')
            if the dataset already has an ``is_terminal`` column. When True, the
            existing columns are dropped and rewritten.

    Returns:
        ``{"episodes_processed": int, "is_terminal_count": int, "is_last_count": int}``.
    """
    root = Path(dataset_path)
    files = _data_parquet_files(root)
    if not files:
        raise FileNotFoundError(f"No data parquet files in {root}")

    first_schema = pq.read_schema(files[0])
    if _TERMINAL_COL in first_schema.names and not overwrite:
        raise ValueError("already_stamped")

    # First pass: read (episode_index, observation.state) for every frame.
    # Memory footprint is bounded by the dataset's data parquet size, which the
    # loader already handles today (dataset_service loads it for charts/episodes).
    all_ep: list[int] = []
    all_states_chunks: list[pa.Array] = []
    for f in files:
        table = pq.read_table(f, columns=["episode_index", "observation.state"])
        all_ep.extend(table.column("episode_index").to_pylist())
        # Keep each chunk's state as a pyarrow array — we only need it to build
        # the numpy view below. Avoid to_pylist() on the whole dataset.
        all_states_chunks.append(table.column("observation.state").combine_chunks())

    import numpy as np
    states = np.concatenate([np.asarray(a.to_pylist(), dtype=np.float32) for a in all_states_chunks], axis=0)
    ep_arr = np.asarray(all_ep, dtype=np.int64)
    total_frames = len(ep_arr)

    is_terminal = np.zeros(total_frames, dtype=bool)
    is_last = np.zeros(total_frames, dtype=bool)

    episodes_processed = 0
    unique_eps = np.unique(ep_arr)
    for ep in unique_eps:
        rows = np.where(ep_arr == ep)[0]
        if len(rows) == 0:
            continue
        episodes_processed += 1
        is_last[rows[-1]] = True
        ends_local = detect_cycle_ends(states[rows])
        for local_idx in ends_local:
            is_terminal[rows[local_idx]] = True

    # Second pass: rewrite each parquet with the new (or replaced) flag columns.
    offset = 0
    for f in files:
        table = pq.read_table(f)
        n = table.num_rows
        term_chunk = pa.array(is_terminal[offset:offset + n], type=pa.bool_())
        last_chunk = pa.array(is_last[offset:offset + n], type=pa.bool_())

        new_table = table
        for name in (_TERMINAL_COL, _LAST_COL):
            if name in new_table.schema.names:
                new_table = new_table.drop([name])
        new_table = new_table.append_column(_LAST_COL, last_chunk)
        new_table = new_table.append_column(_TERMINAL_COL, term_chunk)

        tmp_path = f.with_suffix(f.suffix + ".tmp")
        pq.write_table(new_table, tmp_path)
        os.replace(tmp_path, f)
        offset += n

    return {
        "episodes_processed": episodes_processed,
        "is_terminal_count": int(is_terminal.sum()),
        "is_last_count": int(is_last.sum()),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cycle_stamp_service.py -v`
Expected: PASS (10 tests total).

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/services/cycle_stamp_service.py tests/test_cycle_stamp_service.py
git commit -m "feat(cycle-stamp): atomically rewrite parquets with cycle flags"
```

---

### Task 3: Wire stamp op into DatasetOpsService

**Files:**
- Modify: `backend/datasets/services/dataset_ops_service.py`

Plugs `stamp_dataset_cycles` into the existing job registry so the frontend can poll it just like split/merge/delete.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cycle_stamp_service.py`:

```python
import asyncio

from backend.datasets.services.dataset_ops_service import dataset_ops_service


class TestOpsServiceIntegration:
    def test_stamp_cycles_queues_and_completes(self, tmp_path):
        ds = tmp_path / "ds"
        _write_fake_dataset(ds, [
            {"length": 6,
             "left_trace": [1.0, 0.3, 1.0, 1.0, 1.0, 1.0],
             "right_trace": [1.0] * 6},
        ])

        async def run() -> str:
            return await dataset_ops_service.stamp_cycles(source_path=ds, overwrite=False)

        job_id = asyncio.run(run())
        # Wait up to 2s for the executor job to finish (synthetic dataset is tiny).
        import time
        deadline = time.time() + 2.0
        while time.time() < deadline:
            status = dataset_ops_service.get_job_status(job_id)
            if status and status["status"] in ("complete", "failed"):
                break
            time.sleep(0.02)

        status = dataset_ops_service.get_job_status(job_id)
        assert status is not None
        assert status["operation"] == "stamp_cycles"
        assert status["status"] == "complete", status.get("error")
        assert status["result_path"] == str(ds)

    def test_stamp_cycles_reports_already_stamped(self, tmp_path):
        ds = tmp_path / "ds"
        _write_fake_dataset(ds, [
            {"length": 4, "left_trace": [1.0] * 4, "right_trace": [1.0] * 4},
        ])

        async def run_twice() -> tuple[str, str]:
            first = await dataset_ops_service.stamp_cycles(source_path=ds, overwrite=False)
            # let the first job finish before submitting the second
            for _ in range(200):
                s = dataset_ops_service.get_job_status(first)
                if s and s["status"] in ("complete", "failed"):
                    break
                await asyncio.sleep(0.01)
            second = await dataset_ops_service.stamp_cycles(source_path=ds, overwrite=False)
            return first, second

        first, second = asyncio.run(run_twice())
        # Wait for second to settle.
        import time
        deadline = time.time() + 2.0
        while time.time() < deadline:
            s = dataset_ops_service.get_job_status(second)
            if s and s["status"] in ("complete", "failed"):
                break
            time.sleep(0.02)

        status = dataset_ops_service.get_job_status(second)
        assert status["status"] == "failed"
        assert status["error"] == "already_stamped"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cycle_stamp_service.py::TestOpsServiceIntegration -v`
Expected: FAIL — `DatasetOpsService` has no `stamp_cycles` attribute.

- [ ] **Step 3: Add the method to the service**

Edit `backend/datasets/services/dataset_ops_service.py`. Add this method inside `DatasetOpsService`, next to `merge_datasets` (before the "Blocking workers" header):

```python
    async def stamp_cycles(
        self,
        source_path: str | Path,
        overwrite: bool,
    ) -> str:
        """Queue an in-place cycle-stamp job. Returns the job ID."""
        job = self._create_job("stamp_cycles")
        job_id = job["id"]

        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None, self._run_stamp_cycles, job_id, Path(source_path), overwrite
        )
        return job_id
```

Then add this blocking worker at the end of the class (after `_run_split_and_merge`):

```python
    def _run_stamp_cycles(
        self,
        job_id: str,
        source_path: Path,
        overwrite: bool,
    ) -> None:
        from backend.datasets.services import cycle_stamp_service

        job = self._jobs[job_id]
        job["status"] = "running"
        try:
            cycle_stamp_service.stamp_dataset_cycles(source_path, overwrite=overwrite)
            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(source_path)
            logger.info("Stamp cycles job %s complete: %s", job_id, source_path)
        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Stamp cycles job %s failed", job_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cycle_stamp_service.py -v`
Expected: PASS (12 tests total, including the 2 new integration tests).

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/services/dataset_ops_service.py tests/test_cycle_stamp_service.py
git commit -m "feat(cycle-stamp): queue stamp_cycles through DatasetOpsService"
```

---

### Task 4: Router endpoints

**Files:**
- Modify: `backend/datasets/routers/dataset_ops.py`
- Modify: `tests/test_dataset_ops_router.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dataset_ops_router.py` (before the file's last existing class if there's one, otherwise at the end):

```python
# ---------------------------------------------------------------------------
# POST /api/datasets/stamp-cycles
# ---------------------------------------------------------------------------


class TestStampCycles:
    @pytest.mark.asyncio
    async def test_returns_202_with_job(self, client, tmp_path):
        source = tmp_path / "ds"
        source.mkdir()

        with patch.object(
            dataset_ops_service,
            "stamp_cycles",
            new_callable=AsyncMock,
            return_value="xyz-789",
        ):
            resp = await client.post(
                "/api/datasets/stamp-cycles",
                json={"source_path": str(source), "overwrite": False},
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["job_id"] == "xyz-789"
        assert data["operation"] == "stamp_cycles"
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_404_if_source_missing(self, client):
        resp = await client.post(
            "/api/datasets/stamp-cycles",
            json={"source_path": "/nonexistent/path", "overwrite": False},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_rejects_path_outside_allowed_roots(self, client):
        # Path exists but is not under any allowed dataset root.
        resp = await client.post(
            "/api/datasets/stamp-cycles",
            json={"source_path": "/etc", "overwrite": False},
        )
        assert resp.status_code == 400


class TestStampCyclesStatus:
    @pytest.mark.asyncio
    async def test_status_returns_describe(self, client, tmp_path):
        source = tmp_path / "ds"
        source.mkdir()

        with patch(
            "backend.datasets.routers.dataset_ops.describe_stamp_state",
            return_value={"stamped": True, "is_terminal_count_sample": 42},
        ):
            resp = await client.get(
                "/api/datasets/stamp-cycles/status",
                params={"path": str(source)},
            )

        assert resp.status_code == 200
        assert resp.json() == {"stamped": True, "is_terminal_count_sample": 42}

    @pytest.mark.asyncio
    async def test_status_404_if_path_missing(self, client):
        resp = await client.get(
            "/api/datasets/stamp-cycles/status",
            params={"path": "/nonexistent/path"},
        )
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dataset_ops_router.py::TestStampCycles tests/test_dataset_ops_router.py::TestStampCyclesStatus -v`
Expected: FAIL — endpoints return 404 (route not found).

- [ ] **Step 3: Add the router endpoints**

Edit `backend/datasets/routers/dataset_ops.py`. First add the new import at the top of the file (after the existing `dataset_ops_service` import):

```python
from backend.core.config import settings
from backend.datasets.services.cycle_stamp_service import describe_stamp_state
```

Replace the existing `_validate_path` helper (lines 12-14) with a stricter version that also checks `allowed_dataset_roots`:

```python
def _validate_path(path_str: str) -> Path:
    """Resolve and reject paths outside the configured allowed dataset roots."""
    resolved = Path(path_str).resolve()
    allowed_roots = [Path(p).resolve() for p in settings.allowed_dataset_roots]
    if not any(resolved.is_relative_to(r) for r in allowed_roots):
        raise HTTPException(
            status_code=400,
            detail=f"Path is not under any allowed dataset root: {resolved}",
        )
    return resolved
```

Note: split/merge/delete already call `_validate_path` but throw away the return value — tightening this helper strengthens those endpoints without breaking them. All `tmp_path` fixtures in `tests/test_dataset_ops_router.py` are already appended to `allowed_dataset_roots` by the existing `_allow_tmp_paths` fixture, so pre-existing tests stay green.

Add this schema near the other request schemas:

```python
class StampCyclesRequest(BaseModel):
    source_path: str
    overwrite: bool = False
```

Add these endpoints at the end of the file:

```python
@router.post("/stamp-cycles", response_model=JobResponse, status_code=202)
async def stamp_cycles(req: StampCyclesRequest):
    """Stamp is_terminal + is_last columns onto a dataset's parquet files in place."""
    source = _validate_path(req.source_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Source path not found: {req.source_path}")

    job_id = await dataset_ops_service.stamp_cycles(
        source_path=str(source), overwrite=req.overwrite,
    )
    return JobResponse(job_id=job_id, operation="stamp_cycles", status="queued")


@router.get("/stamp-cycles/status")
async def stamp_cycles_status(path: str):
    """Cheap probe — does the dataset already carry cycle-stamp columns?"""
    source = _validate_path(path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {path}")
    return describe_stamp_state(source)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dataset_ops_router.py -v`
Expected: PASS — 13 existing + 5 new tests.

- [ ] **Step 5: Commit**

```bash
git add backend/datasets/routers/dataset_ops.py tests/test_dataset_ops_router.py
git commit -m "feat(cycle-stamp): expose stamp-cycles + status endpoints"
```

---

### Task 5: Frontend `CyclesTab`

**Files:**
- Modify: `frontend/src/components/TrimPanel.tsx`

- [ ] **Step 1: Extend `TabId` and add the `Cycles` tab button**

In `frontend/src/components/TrimPanel.tsx`, update the type alias near the top:

```tsx
type TabId = 'split' | 'merge' | 'delete' | 'cycles'
```

Locate the final component `export function TrimPanel(...)` at the bottom. Update the tab-button loop so `'cycles'` is rendered as a fourth tab. Replace:

```tsx
        {(['split', 'merge', 'delete'] as TabId[]).map(t => (
```

with:

```tsx
        {(['split', 'merge', 'delete', 'cycles'] as TabId[]).map(t => (
```

Then add a route for the new tab next to the other `tab === ...` conditionals:

```tsx
        {tab === 'cycles' && <CyclesTab datasetPath={datasetPath} />}
```

- [ ] **Step 2: Add the `CyclesTab` component**

In the same file, paste the following component definition immediately before `export function TrimPanel(...)`:

```tsx
interface StampStatus {
  stamped: boolean
  is_terminal_count_sample: number
}

function CyclesTab({ datasetPath }: { datasetPath: string | null }) {
  const [status, setStatus] = useState<StampStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(false)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { jobStatus, polling, startPolling, reset } = useJobPoller()

  const refreshStatus = useCallback(async () => {
    if (!datasetPath) return
    setStatusLoading(true)
    setStatusError(null)
    try {
      const resp = await client.get<StampStatus>('/datasets/stamp-cycles/status', {
        params: { path: datasetPath },
      })
      setStatus(resp.data)
    } catch {
      setStatusError('Failed to read stamp status')
      setStatus(null)
    } finally {
      setStatusLoading(false)
    }
  }, [datasetPath])

  useEffect(() => { void refreshStatus() }, [refreshStatus])

  // When a job completes, refresh the stamp-state probe so the UI updates
  // without a manual reload. Accept both "complete" (what the existing
  // dataset_ops_service writes) and "completed" (what the existing poller
  // expects) so this works regardless of which convention future cleanup
  // settles on.
  useEffect(() => {
    const s = jobStatus?.status
    if (s === 'complete' || s === 'completed') {
      void refreshStatus()
    }
  }, [jobStatus?.status, refreshStatus])

  const submit = useCallback(async (overwrite: boolean) => {
    if (!datasetPath) return
    setSubmitting(true)
    setSubmitError(null)
    reset()
    try {
      const resp = await client.post<{ job_id: string; operation: string; status: string }>(
        '/datasets/stamp-cycles',
        { source_path: datasetPath, overwrite },
      )
      startPolling(resp.data.job_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Stamp failed'
      setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }, [datasetPath, reset, startPolling])

  const onPrimaryClick = () => {
    if (status?.stamped) {
      setConfirmOpen(true)
    } else {
      void submit(false)
    }
  }

  if (!datasetPath) {
    return <div style={s.emptyState}>Load a dataset first to stamp cycles.</div>
  }

  return (
    <div style={s.tabContent}>
      <div style={s.matchPreview}>
        {statusLoading && <span style={{ color: 'var(--text-dim)' }}>Checking current state…</span>}
        {statusError && <span style={s.errorText}>{statusError}</span>}
        {!statusLoading && !statusError && status && (
          status.stamped
            ? <span style={{ color: 'var(--c-yellow)' }}>
                Already stamped — {status.is_terminal_count_sample} is_terminal flags in the first parquet.
              </span>
            : <span style={{ color: 'var(--text-muted)' }}>
                No cycle markers yet. Stamping rewrites data parquet files in place.
              </span>
        )}
      </div>

      {submitError && <div style={s.errorText}>{submitError}</div>}

      <button
        style={{ ...s.actionBtn, opacity: submitting || polling ? 0.6 : 1 }}
        onClick={onPrimaryClick}
        disabled={submitting || polling || statusLoading}
      >
        {submitting
          ? 'Submitting…'
          : status?.stamped
            ? 'Overwrite cycle markers'
            : 'Stamp cycles'}
      </button>

      <JobProgress jobStatus={jobStatus} polling={polling} />

      {confirmOpen && (
        <div style={s.matchPreview}>
          <span style={{ color: 'var(--c-yellow)' }}>
            This replaces the existing is_terminal / is_last columns in place. Continue?
          </span>
          <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
            <button
              style={{ ...s.actionBtn, background: 'var(--c-red)' }}
              onClick={() => { setConfirmOpen(false); void submit(true) }}
              disabled={submitting}
            >
              Overwrite
            </button>
            <button
              style={{ ...s.refreshBtn, padding: '6px 12px' }}
              onClick={() => setConfirmOpen(false)}
              disabled={submitting}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Type-check the frontend**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: No new errors in `TrimPanel.tsx`. Pre-existing errors in other files (e.g. `OverviewTab.tsx`, per the notes in commit b8b8ff7) are not introduced by this task — if any, leave them alone.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/TrimPanel.tsx
git commit -m "feat(cycle-stamp): add Cycles tab to TrimPanel"
```

---

### Task 6: End-to-end smoke verification

**Files:**
- None (manual test, optional commit of dataset if you want to save the stamped state in git — normally you don't).

- [ ] **Step 1: Remove the flags we stamped earlier with the external script**

We ran `update_dataset_flags.py` by hand during debugging. To make sure the new integrated path is what actually works, delete the columns and let the new UI re-stamp from scratch.

Run:

```bash
cd /home/tommoro/jm_ws/local_data_pipline/lerobot_dataset_helper
python3 -c "
from lerobot_dataset_helper.core import delete_field_from_data_parquet
for f in ('is_terminal', 'is_last'):
    try:
        delete_field_from_data_parquet('/mnt/synology/data/data_div/2026_1/lerobot/cell002/HZ_seqpick_deodorant', f)
        print(f'dropped {f}')
    except Exception as exc:
        print(f'{f}: {exc}')
"
```

Expected: "dropped is_terminal" and "dropped is_last".

- [ ] **Step 2: Start the backend + frontend**

Run: `./start.sh` (or whatever the project's local dev command is).
Expected: FastAPI on `127.0.0.1:8001`, Vite on `http://localhost:5173`, no startup errors.

- [ ] **Step 3: Exercise the new tab**

1. In the browser, open a cell002 dataset (`HZ_seqpick_deodorant`).
2. Select any episode; confirm the terminal-bar and scrubber show no tick marks (flags are gone).
3. Open the `Trim` panel → `Cycles` tab.
4. Expect the status line: "No cycle markers yet…" and a "Stamp cycles" button.
5. Click the button, watch the `JobProgress` component flip `QUEUED → RUNNING → COMPLETED`.
6. After completion, the status line should update to "Already stamped — N is_terminal flags…".
7. Reload the episode (click a different episode then back). The terminal-bar should now show `6.9s, 18.4s, …` chips and the scrubber should show red tick marks.
8. Click "Overwrite cycle markers" → confirm in the modal → watch it complete again with the same result.

Expected behaviour: all of the above. If the tick marks fail to appear after a successful job, check the dataset_service cache — the next task is a defensive commit that clears it, but manual reload via the episode picker should be enough for step 7.

- [ ] **Step 4: Commit the plan's checklist status**

```bash
git add docs/superpowers/plans/2026-04-17-cycle-stamp-integration.md
git commit -m "chore: mark cycle-stamp plan steps complete"
```

---

## Follow-up (out of scope for this plan)

- Make gripper thresholds / channel indices configurable per robot type. Today they are hardcoded to the `HZ_seqpick_deodorant` rby1a arm.
- Consider retiring the external `lerobot_dataset_helper/update_dataset_flags.py` once the in-app path is proven in production (or dropping the external dep via a tombstone comment that points to the new service).
- Add an e2e playwright test for the Cycles tab — hook into the existing `tests/test_e2e.py` harness.
