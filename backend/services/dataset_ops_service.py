"""Service for dataset split and merge operations using LeRobot dataset_tools.

Wraps LeRobot's split_dataset and merge_datasets with async job tracking.
All blocking LeRobot operations run in a thread executor to avoid blocking
the async event loop. Results are written to local paths only.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _set_writable_cache() -> None:
    """Redirect HF datasets cache to a writable location."""
    cache_dir = Path(tempfile.gettempdir()) / "hf-datasets-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_DATASETS_CACHE"] = str(cache_dir)
    os.environ["HF_HOME"] = str(cache_dir / "hub")


def _make_writable_mirror(source: Path) -> Path:
    """Create a writable mirror of a dataset using symlinks.

    The datasets library creates .cache dirs next to parquet files.
    If the source is read-only this fails. We create a temp directory
    that mirrors the structure with symlinks to actual files.

    Returns path to the writable mirror. Caller must clean up with shutil.rmtree().
    """
    mirror = Path(tempfile.mkdtemp(prefix="ds-mirror-"))
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target = mirror / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(item)
    return mirror


logger = logging.getLogger(__name__)


class DatasetOpsService:
    """Manages dataset split/merge operations with async job tracking."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Job tracking
    # ------------------------------------------------------------------

    def _create_job(self, operation: str) -> dict[str, Any]:
        job: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "operation": operation,
            "status": "queued",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "error": None,
            "result_path": None,
        }
        self._jobs[job["id"]] = job
        return job

    def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        return self._jobs.get(job_id)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def delete_episodes(
        self,
        source_path: str | Path,
        episode_ids: list[int],
        output_dir: str | Path | None = None,
    ) -> str:
        """Queue a delete-episodes job. Returns the job ID."""
        job = self._create_job("delete")
        job_id = job["id"]

        source = Path(source_path)
        out_dir = Path(output_dir) if output_dir else None

        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None,
            self._run_delete,
            job_id,
            source,
            episode_ids,
            out_dir,
        )
        return job_id

    async def split_dataset(
        self,
        source_path: str | Path,
        episode_ids: list[int],
        target_name: str,
        output_dir: str | Path | None = None,
    ) -> str:
        """Queue a split job. Returns the job ID."""
        job = self._create_job("split")
        job_id = job["id"]

        source = Path(source_path)
        out_dir = Path(output_dir) if output_dir else source.parent / target_name

        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None,
            self._run_split,
            job_id,
            source,
            episode_ids,
            out_dir,
        )
        return job_id

    async def split_and_merge(
        self,
        source_path: str | Path,
        episode_ids: list[int],
        target_path: str | Path,
        target_name: str,
    ) -> str:
        """Queue a split-into-existing job. Returns the job ID."""
        job = self._create_job("split_and_merge")
        job_id = job["id"]

        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None,
            self._run_split_and_merge,
            job_id,
            Path(source_path),
            episode_ids,
            Path(target_path),
            target_name,
        )
        return job_id

    async def merge_datasets(
        self,
        source_paths: list[str | Path],
        target_name: str,
        output_dir: str | Path | None = None,
    ) -> str:
        """Queue a merge job. Returns the job ID."""
        job = self._create_job("merge")
        job_id = job["id"]

        sources = [Path(p) for p in source_paths]
        out_dir = Path(output_dir) if output_dir else sources[0].parent / target_name

        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            None,
            self._run_merge,
            job_id,
            sources,
            out_dir,
        )
        return job_id

    # ------------------------------------------------------------------
    # Blocking workers (run in thread executor)
    # ------------------------------------------------------------------

    def _run_delete(
        self,
        job_id: str,
        source_path: Path,
        episode_ids: list[int],
        output_dir: Path | None,
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = "running"

        try:
            _set_writable_cache()
            from lerobot.datasets.lerobot_dataset import LeRobotDataset
            from lerobot.datasets.dataset_tools import delete_episodes

            mirror = _make_writable_mirror(source_path)
            try:
                dataset = LeRobotDataset(repo_id=f"local/{source_path.name}", root=mirror)

                if output_dir is not None:
                    # Write to a separate output directory
                    result_ds = delete_episodes(
                        dataset,
                        episode_indices=episode_ids,
                        output_dir=output_dir,
                        repo_id=f"local/{output_dir.name}",
                    )
                    result_path = output_dir
                else:
                    # Overwrite source in-place: write to temp, then replace
                    tmp_parent = Path(tempfile.mkdtemp(prefix="delete-parent-"))
                    tmp = tmp_parent / source_path.name
                    # tmp doesn't exist yet — LeRobot will create it
                    result_ds = delete_episodes(
                        dataset,
                        episode_indices=episode_ids,
                        output_dir=tmp,
                        repo_id=f"local/{source_path.name}",
                    )
                    # Replace source with result
                    shutil.rmtree(source_path)
                    shutil.copytree(str(tmp), str(source_path))
                    shutil.rmtree(tmp_parent, ignore_errors=True)
                    result_path = source_path
            finally:
                shutil.rmtree(mirror, ignore_errors=True)

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(result_path)
            logger.info("Delete job %s complete: %s", job_id, result_path)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Delete job %s failed", job_id)

    def _run_split(
        self,
        job_id: str,
        source_path: Path,
        episode_ids: list[int],
        output_path: Path,
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = "running"
        temp_dir: Path | None = None

        try:
            _set_writable_cache()
            from lerobot.datasets.lerobot_dataset import LeRobotDataset
            from lerobot.datasets.dataset_tools import split_dataset

            output_path.mkdir(parents=True, exist_ok=True)
            temp_dir = Path(tempfile.mkdtemp(prefix="split-tmp-"))

            mirror = _make_writable_mirror(source_path)
            try:
                dataset = LeRobotDataset(repo_id=f"local/{source_path.name}", root=mirror)
                result = split_dataset(dataset, splits={"selected": episode_ids}, output_dir=temp_dir)
                split_ds = result["selected"]

                # Move result to output_path
                shutil.copytree(str(temp_dir / "selected"), str(output_path), dirs_exist_ok=True)
                logger.info("Split result written to: %s", output_path)
            finally:
                shutil.rmtree(mirror, ignore_errors=True)

            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir = None

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(output_path)
            logger.info("Split job %s complete: %s", job_id, output_path)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Split job %s failed", job_id)
            if temp_dir is not None and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_merge(
        self,
        job_id: str,
        source_paths: list[Path],
        output_path: Path,
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = "running"
        temp_dir: Path | None = None

        try:
            _set_writable_cache()
            from lerobot.datasets.lerobot_dataset import LeRobotDataset
            from lerobot.datasets.dataset_tools import merge_datasets

            output_path.mkdir(parents=True, exist_ok=True)
            temp_dir = Path(tempfile.mkdtemp(prefix="merge-tmp-"))

            mirrors = []
            try:
                ds_list = []
                for p in source_paths:
                    m = _make_writable_mirror(p)
                    mirrors.append(m)
                    ds_list.append(LeRobotDataset(repo_id=f"local/{p.name}", root=m))

                repo_id = f"local/{output_path.name}"
                merged_ds = merge_datasets(ds_list, output_repo_id=repo_id, output_dir=temp_dir)

                shutil.copytree(str(temp_dir / output_path.name), str(output_path), dirs_exist_ok=True)
                logger.info("Merge result written to: %s", output_path)
            finally:
                for m in mirrors:
                    shutil.rmtree(m, ignore_errors=True)

            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir = None

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(output_path)
            logger.info("Merge job %s complete: %s", job_id, output_path)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Merge job %s failed", job_id)
            if temp_dir is not None and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_split_and_merge(
        self,
        job_id: str,
        source_path: Path,
        episode_ids: list[int],
        target_path: Path,
        target_name: str,
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = "running"
        split_tmp: Path | None = None
        merge_tmp: Path | None = None

        try:
            _set_writable_cache()
            from lerobot.datasets.lerobot_dataset import LeRobotDataset
            from lerobot.datasets.dataset_tools import split_dataset, merge_datasets

            source_mirror = _make_writable_mirror(source_path)
            target_mirror = _make_writable_mirror(target_path)
            try:
                # Step 1: Split selected episodes
                split_tmp = Path(tempfile.mkdtemp(prefix="split-tmp-"))
                source_ds = LeRobotDataset(repo_id=f"local/{source_path.name}", root=source_mirror)
                split_result = split_dataset(source_ds, splits={"selected": episode_ids}, output_dir=split_tmp)
                split_ds = split_result["selected"]

                # Step 2: Merge split result with existing target
                merge_tmp = Path(tempfile.mkdtemp(prefix="merge-tmp-"))
                target_ds = LeRobotDataset(repo_id=f"local/{target_path.name}", root=target_mirror)
                repo_id = f"local/{target_name}"
                merged_ds = merge_datasets([target_ds, split_ds], output_repo_id=repo_id, output_dir=merge_tmp)

                # Step 3: Replace target in-place with merged result
                merged_src = merge_tmp / target_name
                shutil.copytree(str(merged_src), str(target_path), dirs_exist_ok=True)
                logger.info("Split-and-merge result written to: %s", target_path)
            finally:
                shutil.rmtree(source_mirror, ignore_errors=True)
                shutil.rmtree(target_mirror, ignore_errors=True)

            if split_tmp is not None and split_tmp.exists():
                shutil.rmtree(split_tmp, ignore_errors=True)
            shutil.rmtree(merge_tmp, ignore_errors=True)
            merge_tmp = None

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(target_path)
            logger.info("Split-and-merge job %s complete: %s", job_id, target_path)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Split-and-merge job %s failed", job_id)
            if split_tmp is not None and split_tmp.exists():
                shutil.rmtree(split_tmp, ignore_errors=True)
            if merge_tmp is not None and merge_tmp.exists():
                shutil.rmtree(merge_tmp, ignore_errors=True)


dataset_ops_service = DatasetOpsService()
