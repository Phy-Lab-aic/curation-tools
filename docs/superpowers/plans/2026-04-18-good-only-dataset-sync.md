# Good-only Dataset Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current split/new-vs-existing flow with a good-only sync flow that sends selected good episodes to one absolute destination path, with the filesystem policy owned by `rosbag-to-lerobot` and reused from `curation-tools`.

**Architecture:** The work is split across two repositories. `rosbag-to-lerobot` gets a reusable Python sync module that can create a new LeRobot dataset or merge into an existing one while skipping duplicate `Serial_number`s. `curation-tools` stays the UI/API surface: it filters to good episodes plus optional tags, validates the absolute destination path, loads the shared module through a configured sibling checkout path, and reports async job summaries.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pyarrow, React 19, TypeScript 5, Vite 6, Dockerized pytest for `rosbag-to-lerobot`

---

## File Structure

### `rosbag-to-lerobot`

- Create: `/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/conversion/dataset_sync.py`
  - Own the reusable path-driven dataset sync implementation.
- Create: `/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/test/test_dataset_sync.py`
  - Regression coverage for create, merge, duplicate skip, invalid destination, and self-merge.

### `curation-tools`

- Modify: `backend/core/config.py`
  - Add the configured sibling checkout path for `rosbag-to-lerobot`.
- Create: `backend/datasets/services/rosbag_dataset_sync.py`
  - Load and memoize the shared Python API from the sibling repo.
- Modify: `backend/datasets/services/dataset_ops_service.py`
  - Replace the current split-and-merge worker with a sync job that stores summary counts.
- Modify: `backend/datasets/routers/dataset_ops.py`
  - Replace `target_name` / `target_path` / `output_dir` with `destination_path` for the operator sync flow.
- Modify: `frontend/src/components/TrimPanel.tsx`
  - Remove grade toggle and destination mode toggle; keep tag refinement within the good subset; add absolute destination path input and result summary rendering.
- Modify: `tests/test_dataset_ops_router.py`
  - Cover the new request/response contract and error cases.
- Modify: `tests/test_dataset_ops_service.py`
  - Cover loader-backed sync job creation and status summary persistence.

## Task 1: Prepare Isolated Worktrees And Baselines

**Files:**
- Modify: none
- Test: `/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/test/test_batch_flush.py`
- Test: `tests/test_dataset_ops_service.py`

- [ ] **Step 1: Create the `rosbag-to-lerobot` worktree**

Run:
```bash
cd /home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot
git worktree add .worktrees/good-dataset-sync -b feature/good-dataset-sync
```

Expected: `Preparing worktree (new branch 'feature/good-dataset-sync')`

- [ ] **Step 2: Confirm the existing `curation-tools` worktree is clean**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync
git status --short
```

Expected: no output before implementation starts.

- [ ] **Step 3: Run the `rosbag-to-lerobot` baseline test that already exercises serial dedup primitives**

Run:
```bash
cd /home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/.worktrees/good-dataset-sync
docker run --rm -v "$PWD":/app -w /app convert-server-convert-server:latest \
  python3 -m pytest test/test_batch_flush.py -k "HasEpisode" -v
```

Expected: passing tests; no import failures.

- [ ] **Step 4: Run the `curation-tools` async job baseline**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync
python -m pytest tests/test_dataset_ops_service.py -v
```

Expected: `7 passed` before any edits.

- [ ] **Step 5: Commit nothing yet**

Do not create a commit in this setup task. The first commit should happen only after code or tests change.

## Task 2: Add `rosbag-to-lerobot` Sync Regression Tests First

**Files:**
- Create: `/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/test/test_dataset_sync.py`
- Test: `/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/test/test_dataset_sync.py`

- [ ] **Step 1: Write the failing test file**

Add this test file:

```python
from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from conversion.data_creator import DataCreator
from conversion.dataset_sync import SyncResult, sync_selected_episodes


def _make_creator(tmp_path: Path, repo_id: str) -> DataCreator:
    joint_order = {
        "obs": ["j0", "j1", "j2"],
        "action": {"action": ["a0", "a1", "a2"]},
    }
    return DataCreator(
        repo_id=repo_id,
        root=str(tmp_path / repo_id.replace("/", "_")),
        robot_type="test_robot",
        action_order=["action"],
        joint_order=joint_order,
        camera_names=["cam0"],
        fps=10,
        use_videos=True,
    )


def _make_episode(n_frames: int = 6, serial: str = "SN001") -> dict:
    rng = np.random.default_rng(abs(hash(serial)) % (2**32))
    return {
        "obs": rng.random((n_frames, 3), dtype=np.float32),
        "action": rng.random((n_frames, 3), dtype=np.float32),
        "images": {
            "cam0": [rng.integers(0, 255, (64, 64, 3), dtype=np.uint8) for _ in range(n_frames)]
        },
        "task": "test_task",
    }


def _build_dataset(tmp_path: Path, repo_id: str, serials: list[str]) -> Path:
    creator = _make_creator(tmp_path, repo_id)
    try:
        for serial in serials:
            creator.convert_episode(
                _make_episode(serial=serial),
                custom_metadata={"Serial_number": serial, "grade": "good", "tags": ["keep"]},
            )
        creator.finalize()
        return Path(creator.root)
    finally:
        creator.close()


def _episode_serials(dataset_root: Path) -> list[str]:
    import pyarrow as pa

    files = sorted((dataset_root / "meta" / "episodes").rglob("*.parquet"))
    tables = [pq.read_table(path) for path in files]
    merged = pa.concat_tables(tables, promote_options="default")
    return merged.column("Serial_number").to_pylist()


def test_sync_selected_episodes_creates_new_dataset(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path, "source/create", ["SN001", "SN002", "SN003"])
    destination = tmp_path / "created-sync"

    result = sync_selected_episodes(source, [0, 2], destination)

    assert result == SyncResult(
        mode="create",
        destination_path=str(destination),
        created=2,
        skipped_duplicates=0,
    )
    assert _episode_serials(destination) == ["SN001", "SN003"]


def test_sync_selected_episodes_merges_and_skips_duplicate_serials(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path, "source/merge", ["SN001", "SN002", "SN003"])
    destination = _build_dataset(tmp_path, "target/merge", ["SN003", "SN010"])

    result = sync_selected_episodes(source, [1, 2], destination)

    assert result == SyncResult(
        mode="merge",
        destination_path=str(destination),
        created=1,
        skipped_duplicates=1,
    )
    assert _episode_serials(destination) == ["SN003", "SN010", "SN002"]


def test_sync_selected_episodes_rejects_plain_existing_directory(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path, "source/plain-dir", ["SN001"])
    plain_dir = tmp_path / "plain-dir"
    plain_dir.mkdir()

    with pytest.raises(ValueError, match="existing destination is not a LeRobot dataset"):
        sync_selected_episodes(source, [0], plain_dir)


def test_sync_selected_episodes_rejects_self_merge(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path, "source/self", ["SN001"])

    with pytest.raises(ValueError, match="source and destination must differ"):
        sync_selected_episodes(source, [0], source)
```

- [ ] **Step 2: Run the new test file to verify it fails**

Run:
```bash
cd /home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/.worktrees/good-dataset-sync
docker run --rm -v "$PWD":/app -w /app convert-server-convert-server:latest \
  python3 -m pytest test/test_dataset_sync.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'conversion.dataset_sync'`.

- [ ] **Step 3: Commit the test-only change**

Run:
```bash
cd /home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/.worktrees/good-dataset-sync
git add test/test_dataset_sync.py
git commit -m "test: lock dataset sync create/merge validation behavior"
```

## Task 3: Implement The Shared `rosbag-to-lerobot` Sync Engine

**Files:**
- Create: `/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/conversion/dataset_sync.py`
- Test: `/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/test/test_dataset_sync.py`

- [ ] **Step 1: Write the minimal implementation**

Create `conversion/dataset_sync.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
import json
import shutil
import tempfile
from glob import glob
from pathlib import Path
from typing import Literal

import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(frozen=True)
class SyncResult:
    mode: Literal["create", "merge"]
    destination_path: str
    created: int
    skipped_duplicates: int


def _is_lerobot_dataset(path: Path) -> bool:
    return (path / "meta" / "info.json").is_file()


def read_info(dataset_root: Path) -> dict:
    info_path = dataset_root / "meta" / "info.json"
    with info_path.open("r", encoding="utf-8") as fh:
        return json.loads(fh.read().rstrip("\x00"))


def read_episodes(dataset_root: Path) -> pa.Table:
    files = sorted(glob(str(dataset_root / "meta" / "episodes" / "chunk-*" / "file-*.parquet")))
    tables = [pq.read_table(path) for path in files]
    return pa.concat_tables(tables, promote_options="default")


def _serial_set(episodes: pa.Table) -> set[str]:
    if "Serial_number" not in episodes.schema.names:
        return set()
    return {serial for serial in episodes.column("Serial_number").to_pylist() if serial}


def _selected_rows(source_path: Path, episode_ids: list[int]) -> pa.Table:
    episodes = read_episodes(source_path)
    keep = set(episode_ids)
    mask = pa.array([idx in keep for idx in episodes.column("episode_index").to_pylist()])
    return episodes.filter(mask)


def split_dataset(dataset_root: Path, episode_ids: list[int], output_dir: Path) -> Path:
    from backend.datasets.services.dataset_ops_engine import split_dataset as _split_dataset

    return _split_dataset(dataset_root, episode_ids, output_dir)


def merge_datasets(dataset_roots: list[Path], output_dir: Path) -> Path:
    from backend.datasets.services.dataset_ops_engine import merge_datasets as _merge_datasets

    return _merge_datasets(dataset_roots, output_dir)


def sync_selected_episodes(
    source_dataset: Path,
    episode_ids: list[int],
    destination_path: Path,
) -> SyncResult:
    source_dataset = Path(source_dataset)
    destination_path = Path(destination_path)

    if not destination_path.is_absolute():
        raise ValueError("destination path must be absolute")
    source_dataset = source_dataset.resolve()
    destination_path = destination_path.resolve()
    if source_dataset == destination_path:
        raise ValueError("source and destination must differ")
    if not _is_lerobot_dataset(source_dataset):
        raise ValueError("source dataset is not a LeRobot dataset")

    selected = _selected_rows(source_dataset, episode_ids)
    if len(selected) == 0:
        raise ValueError("episode_ids selected no episodes")

    source_serials = selected.column("Serial_number").to_pylist()

    if not destination_path.exists():
        split_dataset(source_dataset, episode_ids, destination_path)
        return SyncResult(
            mode="create",
            destination_path=str(destination_path),
            created=len(source_serials),
            skipped_duplicates=0,
        )

    if not _is_lerobot_dataset(destination_path):
        raise ValueError("existing destination is not a LeRobot dataset")

    source_info = read_info(source_dataset)
    destination_info = read_info(destination_path)
    if source_info.get("fps") != destination_info.get("fps"):
        raise ValueError("fps mismatch between source and destination")
    if source_info.get("robot_type") != destination_info.get("robot_type"):
        raise ValueError("robot_type mismatch between source and destination")

    existing_serials = _serial_set(read_episodes(destination_path))
    kept_episode_ids = [
        episode_id
        for episode_id, serial in zip(episode_ids, source_serials)
        if serial not in existing_serials
    ]
    skipped_duplicates = len(episode_ids) - len(kept_episode_ids)

    if kept_episode_ids:
        split_tmp = Path(tempfile.mkdtemp(prefix="dataset-sync-split-"))
        merged_tmp = Path(tempfile.mkdtemp(prefix="dataset-sync-merged-"))
        backup = destination_path.with_suffix(destination_path.suffix + ".bak")
        try:
            split_dataset(source_dataset, kept_episode_ids, split_tmp)
            merge_datasets([destination_path, split_tmp], merged_tmp)
            destination_path.rename(backup)
            merged_tmp.rename(destination_path)
            shutil.rmtree(backup, ignore_errors=True)
        except Exception:
            if destination_path.exists():
                shutil.rmtree(destination_path, ignore_errors=True)
            if backup.exists():
                backup.rename(destination_path)
            raise
        finally:
            shutil.rmtree(split_tmp, ignore_errors=True)
            shutil.rmtree(merged_tmp, ignore_errors=True)

    return SyncResult(
        mode="merge",
        destination_path=str(destination_path),
        created=len(kept_episode_ids),
        skipped_duplicates=skipped_duplicates,
    )
```

- [ ] **Step 2: Port the four dataset-op helpers into this file**

Replace the `split_dataset()` and `merge_datasets()` wrappers above with local copies of the helper bodies from `curation-tools/backend/datasets/services/dataset_ops_engine.py`, keeping the `read_info()`, `read_episodes()`, `split_dataset()`, and `merge_datasets()` names exactly as shown in Step 1. After this step, `conversion/dataset_sync.py` must not import anything from `curation-tools`.

- [ ] **Step 3: Run the new sync tests**

Run:
```bash
cd /home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/.worktrees/good-dataset-sync
docker run --rm -v "$PWD":/app -w /app convert-server-convert-server:latest \
  python3 -m pytest test/test_dataset_sync.py -v
```

Expected: PASS.

- [ ] **Step 4: Run the existing dedup-adjacent regression**

Run:
```bash
cd /home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/.worktrees/good-dataset-sync
docker run --rm -v "$PWD":/app -w /app convert-server-convert-server:latest \
  python3 -m pytest test/test_batch_flush.py -k "HasEpisode" -v
```

Expected: PASS; no regression in serial-cache behavior.

- [ ] **Step 5: Commit the shared engine**

Run:
```bash
cd /home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/.worktrees/good-dataset-sync
git add conversion/dataset_sync.py test/test_dataset_sync.py
git commit -m "feat: add path-driven dataset sync with serial dedup"
```

## Task 4: Add `curation-tools` Config And Loader For The Shared Module

**Files:**
- Modify: `backend/core/config.py`
- Create: `backend/datasets/services/rosbag_dataset_sync.py`
- Test: `tests/test_dataset_ops_service.py`

- [ ] **Step 1: Extend the service test with a loader-backed worker contract**

Append these tests to `tests/test_dataset_ops_service.py`:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _FakeSyncResult:
    mode: str
    destination_path: str
    created: int
    skipped_duplicates: int


def test_create_job_includes_summary_slot(service: DatasetOpsService) -> None:
    job = service._create_job("sync_good_episodes")
    assert job["summary"] is None


def test_run_sync_good_episodes_sets_summary(service: DatasetOpsService) -> None:
    source = Path("/tmp/source")
    destination = Path("/tmp/destination")
    job = service._create_job("sync_good_episodes")

    with patch("backend.datasets.services.dataset_ops_service.load_sync_selected_episodes") as loader:
        loader.return_value = (
            lambda src, ids, dst: _FakeSyncResult(
                mode="merge",
                destination_path=str(dst),
                created=2,
                skipped_duplicates=1,
            )
        )
        service._run_sync_good_episodes(job["id"], source, [1, 3, 5], destination)

    saved = service.get_job_status(job["id"])
    assert saved["status"] == "complete"
    assert saved["result_path"] == str(destination)
    assert saved["summary"] == {"mode": "merge", "created": 2, "skipped_duplicates": 1}
```

- [ ] **Step 2: Run the service test file to verify it fails**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync
python -m pytest tests/test_dataset_ops_service.py -v
```

Expected: FAIL because `summary` is missing and `load_sync_selected_episodes` / `_run_sync_good_episodes` do not exist.

- [ ] **Step 3: Add the config field and the loader module**

Change `backend/core/config.py` to:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    dataset_path: str = "/mnt/synology/data/data_div/2026_1/lerobot"
    allowed_dataset_roots: list[str] = [
        "/mnt/synology/data/data_div/2026_1/lerobot",
    ]
    rosbag_to_lerobot_repo_path: str = "/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot"
    host: str = "127.0.0.1"
    fastapi_port: int = 8001
    rerun_grpc_port: int = 9876
    rerun_web_port: int = 9090
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    annotations_path: str = ""
    db_path: str = ""
    enable_rerun: bool = False
    debug: bool = False
    cell_name_pattern: str = "cell*"

    model_config = {"env_prefix": "CURATION_"}


settings = Settings()
```

Create `backend/datasets/services/rosbag_dataset_sync.py`:

```python
from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.core.config import settings

_SYNC_FN: Callable[[Path, list[int], Path], Any] | None = None


def load_sync_selected_episodes() -> Callable[[Path, list[int], Path], Any]:
    global _SYNC_FN
    if _SYNC_FN is not None:
        return _SYNC_FN

    repo_root = Path(settings.rosbag_to_lerobot_repo_path).resolve()
    if not repo_root.is_dir():
        raise RuntimeError(f"rosbag-to-lerobot checkout not found: {repo_root}")

    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)

    module = importlib.import_module("conversion.dataset_sync")
    _SYNC_FN = module.sync_selected_episodes
    return _SYNC_FN
```

- [ ] **Step 4: Update the service job record and worker**

Modify `backend/datasets/services/dataset_ops_service.py` like this:

```python
from backend.datasets.services.rosbag_dataset_sync import load_sync_selected_episodes


    def _create_job(self, operation: str) -> dict[str, Any]:
        job: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "operation": operation,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "error": None,
            "result_path": None,
            "summary": None,
        }
        self._jobs[job["id"]] = job
        return job


    async def sync_good_episodes(
        self,
        source_path: str | Path,
        episode_ids: list[int],
        destination_path: str | Path,
    ) -> str:
        job = self._create_job("sync_good_episodes")
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None,
            self._run_sync_good_episodes,
            job["id"],
            Path(source_path),
            episode_ids,
            Path(destination_path),
        )
        return job["id"]


    def _run_sync_good_episodes(
        self,
        job_id: str,
        source_path: Path,
        episode_ids: list[int],
        destination_path: Path,
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = "running"

        try:
            sync_selected_episodes = load_sync_selected_episodes()
            result = sync_selected_episodes(source_path, episode_ids, destination_path)
            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = result.destination_path
            job["summary"] = {
                "mode": result.mode,
                "created": result.created,
                "skipped_duplicates": result.skipped_duplicates,
            }
        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
```

- [ ] **Step 5: Run the service tests again**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync
python -m pytest tests/test_dataset_ops_service.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit the loader/config change with Lore trailers**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync
git add backend/core/config.py backend/datasets/services/rosbag_dataset_sync.py tests/test_dataset_ops_service.py backend/datasets/services/dataset_ops_service.py
git commit -F - <<'EOF'
Load rosbag-to-lerobot sync code through explicit backend configuration

The sync flow needs a typed Python entrypoint from the sibling repo so the
dataset mutation policy lives there while curation-tools keeps job
tracking and API orchestration local.

Constraint: Shared sync code must come from the configured rosbag-to-lerobot checkout, not a subprocess wrapper
Rejected: Shell out to a CLI script | weaker typing and harder error propagation
Confidence: high
Scope-risk: moderate
Reversibility: clean
Directive: Keep the loader narrow; it should expose the shared sync function, not become a general plugin system
Tested: python -m pytest tests/test_dataset_ops_service.py -v
Not-tested: Startup with an invalid configured sibling path
EOF
```

## Task 5: Replace The Backend `split-into` Contract With `destination_path`

**Files:**
- Modify: `backend/datasets/routers/dataset_ops.py`
- Modify: `backend/datasets/services/dataset_ops_service.py`
- Modify: `tests/test_dataset_ops_router.py`

- [ ] **Step 1: Rewrite the router tests around the new request shape**

Replace the split-into tests with these cases:

```python
class TestSplitIntoDataset:
    @pytest.mark.asyncio
    async def test_split_into_syncs_to_absolute_destination(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()
        destination = tmp_path / "good-sync"

        with patch.object(
            dataset_ops_service,
            "sync_good_episodes",
            new_callable=AsyncMock,
            return_value="sync-job-1",
        ) as sync_good_episodes:
            resp = await client.post(
                "/api/datasets/split-into",
                json={
                    "source_path": str(source),
                    "episode_ids": [0, 1],
                    "destination_path": str(destination),
                },
            )

        assert resp.status_code == 202
        assert resp.json()["operation"] == "sync_good_episodes"
        sync_good_episodes.assert_awaited_once_with(
            source_path=str(source.resolve()),
            episode_ids=[0, 1],
            destination_path=str(destination.resolve()),
        )

    @pytest.mark.asyncio
    async def test_split_into_rejects_relative_destination(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()

        resp = await client.post(
            "/api/datasets/split-into",
            json={
                "source_path": str(source),
                "episode_ids": [0],
                "destination_path": "relative/path",
            },
        )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_split_into_rejects_self_merge(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()

        resp = await client.post(
            "/api/datasets/split-into",
            json={
                "source_path": str(source),
                "episode_ids": [0],
                "destination_path": str(source),
            },
        )

        assert resp.status_code == 400
        assert "source and destination must differ" in resp.json()["detail"]
```

- [ ] **Step 2: Run the router tests to verify they fail**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync
python -m pytest tests/test_dataset_ops_router.py -k "split_into" -v
```

Expected: FAIL because the request model and service method still use the old fields.

- [ ] **Step 3: Replace the request/response schema and route logic**

Change `backend/datasets/routers/dataset_ops.py` to:

```python
class SplitIntoRequest(BaseModel):
    source_path: str
    episode_ids: list[int]
    destination_path: str

    @field_validator("episode_ids")
    @classmethod
    def episode_ids_nonempty(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("episode_ids must not be empty")
        return v

    @field_validator("destination_path")
    @classmethod
    def destination_path_must_be_absolute(cls, v: str) -> str:
        if not Path(v).is_absolute():
            raise ValueError("destination_path must be absolute")
        return v


class JobSummaryResponse(BaseModel):
    mode: str
    created: int
    skipped_duplicates: int


class JobStatusResponse(BaseModel):
    job_id: str
    operation: str
    status: str
    created_at: str
    completed_at: str | None = None
    error: str | None = None
    result_path: str | None = None
    summary: JobSummaryResponse | None = None


@router.post("/split-into", response_model=JobResponse, status_code=202)
async def split_into_dataset(req: SplitIntoRequest):
    source = _validate_path(req.source_path)
    destination = _validate_path(req.destination_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Source path not found: {req.source_path}")
    if source == destination:
        raise HTTPException(status_code=400, detail="source and destination must differ")

    job_id = await dataset_ops_service.sync_good_episodes(
        source_path=str(source),
        episode_ids=req.episode_ids,
        destination_path=str(destination),
    )
    return JobResponse(job_id=job_id, operation="sync_good_episodes", status="queued")


@router.get("/ops/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    job = dataset_ops_service.get_job_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return JobStatusResponse(
        job_id=job["id"],
        operation=job["operation"],
        status=job["status"],
        created_at=job["created_at"],
        completed_at=job.get("completed_at"),
        error=job.get("error"),
        result_path=job.get("result_path"),
        summary=job.get("summary"),
    )
```

- [ ] **Step 4: Remove the old split-and-merge public API**

Delete these members from `backend/datasets/services/dataset_ops_service.py`:

```python
    async def split_and_merge(
        self,
        source_path: str | Path,
        episode_ids: list[int],
        target_path: str | Path,
        target_name: str,
    ) -> str:
        ...

    def _run_split_and_merge(
        self,
        job_id: str,
        source_path: Path,
        episode_ids: list[int],
        target_path: Path,
        target_name: str,
    ) -> None:
        ...
```

Keep the standalone `/merge` endpoint and `merge_datasets()` service untouched.

- [ ] **Step 5: Re-run the backend tests**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync
python -m pytest tests/test_dataset_ops_router.py -k "split_into" -v
python -m pytest tests/test_dataset_ops_service.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit the backend contract change with Lore trailers**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync
git add backend/datasets/routers/dataset_ops.py backend/datasets/services/dataset_ops_service.py tests/test_dataset_ops_router.py tests/test_dataset_ops_service.py
git commit -F - <<'EOF'
Switch split-into to an absolute-path sync contract

The operator flow no longer chooses between new and existing datasets.
Instead, the backend treats split-into as a path-driven sync request and
stores the shared module's create-or-merge summary on the async job.

Constraint: The operator contract is absolute destination path only
Rejected: Preserve target_name/target_path/output_dir in the main sync flow | keeps the old branching UI and policy surface alive
Confidence: high
Scope-risk: moderate
Reversibility: clean
Directive: Do not reintroduce source==destination behavior; reject it before dispatching the sync worker
Tested: python -m pytest tests/test_dataset_ops_router.py -k "split_into" -v; python -m pytest tests/test_dataset_ops_service.py -v
Not-tested: End-to-end shared-module import against the real sibling repo
EOF
```

## Task 6: Simplify `TrimPanel` To Good-Only + Optional Tag + Absolute Path

**Files:**
- Modify: `frontend/src/components/TrimPanel.tsx`
- Test: `frontend/package.json`

- [ ] **Step 1: Replace the split state model**

Change the top of `SplitTab` to:

```tsx
type SyncSummary = {
  mode: string
  created: number
  skipped_duplicates: number
}

interface JobStatus {
  job_id: string
  operation: string
  status: string
  created_at: string
  completed_at: string | null
  error: string | null
  result_path: string | null
  summary?: SyncSummary | null
}

function SplitTab({
  datasetPath,
  episodes,
}: {
  datasetPath: string | null
  episodes: Episode[]
}) {
  const [selectedTags, setSelectedTags] = useState<Set<string>>(new Set())
  const [destinationPath, setDestinationPath] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const { jobStatus, polling, startPolling, reset } = useJobPoller()
```

Delete `SplitMode`, `SplitDestination`, `selectedGrades`, `targetName`, `availableDatasets`, `selectedTargetPath`, and the dataset-list fetch effect from the split tab.

- [ ] **Step 2: Replace the matching logic with good-only plus tag refinement**

Use:

```tsx
  const allTags = Array.from(
    new Set(
      episodes
        .filter(e => e.grade === 'good')
        .flatMap(e => e.tags ?? []),
    ),
  ).sort()

  const goodEpisodes = episodes.filter(e => e.grade === 'good')
  const matchingEpisodes = selectedTags.size === 0
    ? goodEpisodes
    : goodEpisodes.filter(e => (e.tags ?? []).some(tag => selectedTags.has(tag)))
```

Keep `toggleTag()` unchanged.

- [ ] **Step 3: Replace the submit logic and destination UI**

Use this submit handler:

```tsx
  const handleSubmit = async () => {
    if (!datasetPath) return
    if (matchingEpisodes.length === 0) {
      setSubmitError('No good episodes match the selected tags')
      return
    }
    if (!destinationPath.trim()) {
      setSubmitError('Enter an absolute destination path')
      return
    }

    setSubmitting(true)
    setSubmitError(null)
    reset()

    try {
      const resp = await client.post<{ job_id: string; operation: string; status: string }>('/datasets/split-into', {
        source_path: datasetPath,
        episode_ids: matchingEpisodes.map(e => e.episode_index).sort((a, b) => a - b),
        destination_path: destinationPath.trim(),
      })
      startPolling(resp.data.job_id)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Sync failed'
      setSubmitError(msg)
    } finally {
      setSubmitting(false)
    }
  }
```

Replace the destination section with:

```tsx
      <div style={s.fieldLabel}>Destination Path</div>
      <input
        style={s.textInput}
        type="text"
        placeholder="/absolute/path/to/good-sync"
        value={destinationPath}
        onChange={e => setDestinationPath(e.target.value)}
        disabled={submitting || polling}
      />
```

- [ ] **Step 4: Update the copy shown to the operator**

Replace the split tab body copy with:

```tsx
      <div style={s.matchPreview}>
        <span style={{ color: matchingEpisodes.length > 0 ? 'var(--interactive)' : 'var(--text-dim)' }}>
          {matchingEpisodes.length} good episode{matchingEpisodes.length !== 1 ? 's' : ''} selected
        </span>
        {matchingEpisodes.length > 0 && (
          <div style={s.matchRanges}>
            {formatEpisodeRanges(matchingEpisodes.map(e => e.episode_index))}
          </div>
        )}
      </div>

      {jobStatus?.status === 'complete' && jobStatus.summary && (
        <div style={s.matchPreview}>
          <span style={{ color: 'var(--c-green)' }}>
            {jobStatus.summary.created} copied, {jobStatus.summary.skipped_duplicates} skipped as duplicates
          </span>
          <span style={{ color: 'var(--text-muted)' }}>
            Mode: {jobStatus.summary.mode}
          </span>
        </div>
      )}

      <button
        style={{ ...s.actionBtn, opacity: submitting || polling ? 0.6 : 1 }}
        onClick={handleSubmit}
        disabled={submitting || polling}
      >
        {submitting ? 'Submitting...' : 'Sync Good Episodes'}
      </button>
```

- [ ] **Step 5: Build the frontend**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync/frontend
npm run build
```

Expected: Vite build succeeds with no TypeScript errors.

- [ ] **Step 6: Commit the UI simplification with Lore trailers**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync
git add frontend/src/components/TrimPanel.tsx
git commit -F - <<'EOF'
Simplify TrimPanel into a good-only path-driven sync flow

The split tab now models the operator's actual workflow: pick good
episodes, optionally narrow by tag, and sync them to one absolute
destination path while showing duplicate-skip results from the backend.

Constraint: No new frontend test dependency may be introduced for this change
Rejected: Preserve grade and destination-mode toggles | they conflict with the approved operator contract
Confidence: high
Scope-risk: moderate
Reversibility: clean
Directive: Keep tags as a refinement inside the good subset; do not broaden this tab back into a generic grade picker
Tested: cd frontend && npm run build
Not-tested: Browser-click manual smoke check
EOF
```

## Task 7: End-To-End Verification, Graph Rebuild, And Cross-Repo Hygiene

**Files:**
- Modify: none
- Test: `tests/test_dataset_ops_router.py`
- Test: `tests/test_dataset_ops_service.py`
- Test: `/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/test/test_dataset_sync.py`

- [ ] **Step 1: Run the curation-tools backend verification set**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync
python -m pytest tests/test_dataset_ops_router.py -k "split_into" -v
python -m pytest tests/test_dataset_ops_service.py -v
```

Expected: PASS.

- [ ] **Step 2: Run the rosbag-to-lerobot verification set in Docker**

Run:
```bash
cd /home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/.worktrees/good-dataset-sync
docker run --rm -v "$PWD":/app -w /app convert-server-convert-server:latest \
  python3 -m pytest test/test_dataset_sync.py test/test_batch_flush.py -k "dataset_sync or HasEpisode" -v
```

Expected: PASS.

- [ ] **Step 3: Rebuild the graphify knowledge graph for `curation-tools`**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync
python3 -c "from graphify.watch import _rebuild_code; from pathlib import Path; _rebuild_code(Path('.'))"
```

Expected: command exits successfully.

- [ ] **Step 4: Inspect both repos before handoff**

Run:
```bash
cd /home/tommoro/.config/superpowers/worktrees/curation-tools/spec-good-path-sync
git status --short
cd /home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot/.worktrees/good-dataset-sync
git status --short
```

Expected: only the intended tracked files are modified.

- [ ] **Step 5: Prepare the handoff summary**

Use this exact checklist in the final handoff:

```text
Changed files:
- rosbag-to-lerobot/conversion/dataset_sync.py
- rosbag-to-lerobot/test/test_dataset_sync.py
- curation-tools/backend/core/config.py
- curation-tools/backend/datasets/services/rosbag_dataset_sync.py
- curation-tools/backend/datasets/services/dataset_ops_service.py
- curation-tools/backend/datasets/routers/dataset_ops.py
- curation-tools/tests/test_dataset_ops_service.py
- curation-tools/tests/test_dataset_ops_router.py
- curation-tools/frontend/src/components/TrimPanel.tsx

Simplifications made:
- Removed new/existing destination branching from the operator flow
- Fixed split tab to good-only selection with optional tag refinement
- Centralized create-or-merge policy in rosbag-to-lerobot

Remaining risks:
- shared-module import path depends on the configured sibling checkout
- no browser-level frontend smoke test unless run manually
```

## Self-Review Checklist

- Spec coverage:
  - absolute destination path: Tasks 4, 5, 6
  - good-only plus tag refinement: Task 6
  - shared implementation in `rosbag-to-lerobot`: Tasks 2 and 3
  - duplicate skip by `Serial_number`: Tasks 2, 3, 7
  - self-merge rejection: Tasks 2, 3, 5
  - existing plain directory rejection: Tasks 2, 3
- Placeholder scan:
  - no `TODO`, `TBD`, or “similar to task N” references remain
- Type consistency:
  - shared engine API is `sync_selected_episodes(...)`
  - `curation-tools` wrapper API is `sync_good_episodes(...)`
  - job summary shape is always `{mode, created, skipped_duplicates}`
