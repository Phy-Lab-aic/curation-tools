"""Service for dataset split and merge operations using LeRobot dataset_tools.

Wraps LeRobot's split_dataset and merge_datasets with async job tracking
and provenance metadata. All blocking LeRobot operations run in a thread
executor to avoid blocking the async event loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

    async def split_dataset(
        self,
        source_path: str | Path,
        episode_ids: list[int],
        target_name: str,
    ) -> str:
        """Queue a split job. Returns the job ID."""
        job = self._create_job("split")
        job_id = job["id"]

        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            None,
            self._run_split,
            job_id,
            Path(source_path),
            episode_ids,
            target_name,
        )
        return job_id

    async def merge_datasets(
        self,
        source_paths: list[str | Path],
        target_name: str,
    ) -> str:
        """Queue a merge job. Returns the job ID."""
        job = self._create_job("merge")
        job_id = job["id"]

        resolved = [(Path(p)) for p in source_paths]
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            None,
            self._run_merge,
            job_id,
            resolved,
            target_name,
        )
        return job_id

    def list_derived_datasets(self) -> list[dict[str, Any]]:
        """List datasets in the derived_dataset_path directory."""
        from backend.config import settings

        derived_root = Path(settings.derived_dataset_path)
        if not derived_root.exists():
            return []

        results: list[dict[str, Any]] = []
        for child in sorted(derived_root.iterdir()):
            if not child.is_dir():
                continue
            entry: dict[str, Any] = {"name": child.name, "path": str(child)}
            prov_path = child / "provenance.json"
            if prov_path.exists():
                try:
                    entry["provenance"] = json.loads(prov_path.read_text("utf-8"))
                except (json.JSONDecodeError, OSError):
                    entry["provenance"] = None
            results.append(entry)
        return results

    def get_provenance(self, dataset_name: str) -> dict[str, Any] | None:
        """Read provenance.json for a derived dataset."""
        from backend.config import settings

        prov_path = Path(settings.derived_dataset_path) / dataset_name / "provenance.json"
        if not prov_path.exists():
            return None
        try:
            return json.loads(prov_path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    # ------------------------------------------------------------------
    # Blocking workers (run in thread executor)
    # ------------------------------------------------------------------

    def _run_split(
        self,
        job_id: str,
        source_path: Path,
        episode_ids: list[int],
        target_name: str,
    ) -> None:
        from backend.config import settings

        job = self._jobs[job_id]
        job["status"] = "running"
        temp_dir: Path | None = None

        try:
            from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
            from lerobot.datasets.dataset_tools import split_dataset

            derived_root = Path(settings.derived_dataset_path)
            derived_root.mkdir(parents=True, exist_ok=True)

            temp_dir = Path(tempfile.mkdtemp(dir=derived_root, prefix=".split-"))

            source_name = source_path.name
            dataset = LeRobotDataset(repo_id=source_name, root=source_path)
            split_dataset(dataset, splits={"selected": episode_ids}, output_dir=temp_dir)

            target_dir = derived_root / target_name
            temp_dir.rename(target_dir)
            temp_dir = None  # renamed successfully, no cleanup needed

            provenance = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "operation": "split",
                "sources": [
                    {"path": str(source_path), "episode_ids": episode_ids},
                ],
                "target_name": target_name,
                "lerobot_version": "3.0",
            }
            (target_dir / "provenance.json").write_text(
                json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(target_dir)
            logger.info("Split job %s complete: %s", job_id, target_dir)

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
        target_name: str,
    ) -> None:
        from backend.config import settings

        job = self._jobs[job_id]
        job["status"] = "running"
        temp_dir: Path | None = None

        try:
            from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
            from lerobot.datasets.dataset_tools import merge_datasets

            derived_root = Path(settings.derived_dataset_path)
            derived_root.mkdir(parents=True, exist_ok=True)

            temp_dir = Path(tempfile.mkdtemp(dir=derived_root, prefix=".merge-"))

            datasets = []
            for p in source_paths:
                datasets.append(LeRobotDataset(repo_id=p.name, root=p))

            merge_datasets(datasets, output_repo_id=target_name, output_dir=temp_dir)

            target_dir = derived_root / target_name
            temp_dir.rename(target_dir)
            temp_dir = None

            provenance = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "operation": "merge",
                "sources": [{"path": str(p)} for p in source_paths],
                "target_name": target_name,
                "lerobot_version": "3.0",
            }
            (target_dir / "provenance.json").write_text(
                json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            job["status"] = "complete"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["result_path"] = str(target_dir)
            logger.info("Merge job %s complete: %s", job_id, target_dir)

        except Exception as exc:
            job["status"] = "failed"
            job["completed_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = str(exc)
            logger.exception("Merge job %s failed", job_id)
            if temp_dir is not None and temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)


dataset_ops_service = DatasetOpsService()
