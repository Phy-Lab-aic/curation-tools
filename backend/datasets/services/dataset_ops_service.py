"""Service for dataset split/merge/delete operations.

Wraps dataset_ops_engine with async job tracking. All blocking operations
run in a thread executor to avoid blocking the async event loop.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.datasets.services import dataset_ops_engine as engine

logger = logging.getLogger(__name__)


class DatasetOpsService:
    """Manages dataset split/merge/delete operations with async job tracking."""

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
        loop.run_in_executor(None, self._run_delete, job_id, source, episode_ids, out_dir)
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
        loop.run_in_executor(None, self._run_split, job_id, source, episode_ids, out_dir)
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
            None, self._run_split_and_merge,
            job_id, Path(source_path), episode_ids, Path(target_path), target_name,
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
        loop.run_in_executor(None, self._run_merge, job_id, sources, out_dir)
        return job_id

    async def stamp_cycles(
        self,
        source_path: str | Path,
        overwrite: bool,
    ) -> str:
        """Queue a cycle-stamping job. Returns the job ID."""
        job = self._create_job("stamp_cycles")
        job_id = job["id"]

        source = Path(source_path)

        loop = asyncio.get_running_loop()
        loop.call_soon(
            loop.run_in_executor,
            None,
            self._run_stamp_cycles,
            job_id,
            source,
            overwrite,
        )
        return job_id

    # ------------------------------------------------------------------
    # Blocking workers (run in thread executor)
    # ------------------------------------------------------------------

    def _run_with_backup(
        self,
        target_path: Path,
        fn,
    ) -> None:
        """Run fn() with backup/restore for in-place operations."""
        backup = target_path.with_suffix(target_path.suffix + ".bak")
        target_path.rename(backup)
        try:
            fn(backup, target_path)
            shutil.rmtree(backup)
        except Exception:
            if target_path.exists():
                shutil.rmtree(target_path)
            backup.rename(target_path)
            raise

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
            in_place = output_dir is None
            if in_place:
                self._run_with_backup(
                    source_path,
                    lambda src, dst: engine.delete_episodes(src, episode_ids, dst),
                )
                result_path = source_path
            else:
                engine.delete_episodes(source_path, episode_ids, output_dir)
                result_path = output_dir

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

        try:
            engine.split_dataset(source_path, episode_ids, output_path)

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(output_path)
            logger.info("Split job %s complete: %s", job_id, output_path)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Split job %s failed", job_id)

    def _run_merge(
        self,
        job_id: str,
        source_paths: list[Path],
        output_path: Path,
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = "running"

        try:
            engine.merge_datasets(source_paths, output_path)

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(output_path)
            logger.info("Merge job %s complete: %s", job_id, output_path)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Merge job %s failed", job_id)

    def _run_stamp_cycles(
        self,
        job_id: str,
        source_path: Path,
        overwrite: bool,
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = "running"

        try:
            from backend.datasets.services import cycle_stamp_service

            def stamp_into_copy(src: Path, dst: Path) -> None:
                shutil.copytree(src, dst)
                cycle_stamp_service.stamp_dataset_cycles(dst, overwrite=overwrite)

            self._run_with_backup(
                source_path,
                stamp_into_copy,
            )

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(source_path)
            logger.info("Stamp-cycles job %s complete: %s", job_id, source_path)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Stamp-cycles job %s failed", job_id)

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

        try:
            import tempfile

            split_tmp = Path(tempfile.mkdtemp(prefix="split-tmp-"))
            engine.split_dataset(source_path, episode_ids, split_tmp)

            self._run_with_backup(
                target_path,
                lambda src, dst: engine.merge_datasets([src, split_tmp], dst),
            )

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(target_path)
            logger.info("Split-and-merge job %s complete: %s", job_id, target_path)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Split-and-merge job %s failed", job_id)

        finally:
            if split_tmp is not None and split_tmp.exists():
                shutil.rmtree(split_tmp, ignore_errors=True)


dataset_ops_service = DatasetOpsService()
