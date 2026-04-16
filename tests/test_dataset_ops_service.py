"""Tests for DatasetOpsService — job tracking and async API."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.datasets.services.dataset_ops_service import DatasetOpsService


@pytest.fixture()
def service() -> DatasetOpsService:
    return DatasetOpsService()


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
    async def test_split_and_merge_returns_job_id(self, service: DatasetOpsService) -> None:
        with patch.object(service, "_run_split_and_merge"):
            job_id = await service.split_and_merge("/tmp/src", [0], "/tmp/tgt", "tgt")
            assert isinstance(job_id, str)


def test_singleton_import() -> None:
    from backend.datasets.services.dataset_ops_service import dataset_ops_service
    assert isinstance(dataset_ops_service, DatasetOpsService)
