"""Tests for DatasetOpsService — job tracking and async API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.datasets.services.dataset_ops_service import DatasetOpsService


@pytest.fixture()
def service() -> DatasetOpsService:
    return DatasetOpsService()


@dataclass(frozen=True)
class _FakeSyncResult:
    mode: str
    destination_path: str
    created: int
    skipped_duplicates: int


class TestJobTracking:
    def test_get_job_status_unknown(self, service: DatasetOpsService) -> None:
        assert service.get_job_status("nonexistent") is None

    def test_create_job_fields(self, service: DatasetOpsService) -> None:
        job = service._create_job("split")
        assert job["operation"] == "split"
        assert job["status"] == "queued"
        assert job["completed_at"] is None
        assert job["error"] is None
        assert job["result_path"] is None
        assert job["summary"] is None
        assert service.get_job_status(job["id"]) is job


class TestPublicAPI:
    @pytest.mark.asyncio
    async def test_delete_returns_job_id(self, service: DatasetOpsService) -> None:
        with patch.object(service, "_run_delete"):
            job_id = await service.delete_episodes("/tmp/ds", [0, 1])
            assert isinstance(job_id, str)
            assert len(job_id) == 36

    @pytest.mark.asyncio
    async def test_split_returns_job_id(self, service: DatasetOpsService) -> None:
        with patch.object(service, "_run_split"):
            job_id = await service.split_dataset("/tmp/ds", [0], "split-out")
            assert isinstance(job_id, str)

    @pytest.mark.asyncio
    async def test_merge_returns_job_id(self, service: DatasetOpsService) -> None:
        with patch.object(service, "_run_merge"):
            job_id = await service.merge_datasets(["/tmp/a", "/tmp/b"], "merged")
            assert isinstance(job_id, str)

    @pytest.mark.asyncio
    async def test_sync_good_episodes_returns_job_id(self, service: DatasetOpsService) -> None:
        with patch.object(service, "_run_sync_good_episodes"):
            job_id = await service.sync_good_episodes("/tmp/src", [0], "/tmp/dest")
            assert isinstance(job_id, str)


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
    assert saved is not None
    assert saved["status"] == "complete"
    assert saved["result_path"] == str(destination)
    assert saved["summary"] == {"mode": "merge", "created": 2, "skipped_duplicates": 1}


def test_singleton_import() -> None:
    from backend.datasets.services.dataset_ops_service import dataset_ops_service
    assert isinstance(dataset_ops_service, DatasetOpsService)
