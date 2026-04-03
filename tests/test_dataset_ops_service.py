"""Tests for DatasetOpsService — mocks LeRobot imports via sys.modules."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.services.dataset_ops_service import DatasetOpsService


@pytest.fixture()
def service() -> DatasetOpsService:
    return DatasetOpsService()


@pytest.fixture()
def derived_dir(tmp_path: Path) -> Path:
    d = tmp_path / "derived-datasets"
    d.mkdir()
    return d


@pytest.fixture()
def mock_lerobot():
    """Inject mock lerobot modules into sys.modules so local imports resolve."""
    mock_LeRobotDataset = MagicMock()
    mock_split_dataset = MagicMock(return_value={})
    mock_merge_datasets = MagicMock(return_value=MagicMock())

    # Build fake module hierarchy
    mod_lerobot = MagicMock()
    mod_common = MagicMock()
    mod_datasets_pkg = MagicMock()
    mod_lerobot_dataset = MagicMock()
    mod_dataset_tools = MagicMock()

    mod_lerobot_dataset.LeRobotDataset = mock_LeRobotDataset
    mod_dataset_tools.split_dataset = mock_split_dataset
    mod_dataset_tools.merge_datasets = mock_merge_datasets

    saved = {}
    modules_to_set = {
        "lerobot": mod_lerobot,
        "lerobot.common": mod_common,
        "lerobot.common.datasets": mod_datasets_pkg,
        "lerobot.common.datasets.lerobot_dataset": mod_lerobot_dataset,
        "lerobot.datasets": MagicMock(),
        "lerobot.datasets.dataset_tools": mod_dataset_tools,
    }

    for key, val in modules_to_set.items():
        saved[key] = sys.modules.get(key)
        sys.modules[key] = val

    yield {
        "LeRobotDataset": mock_LeRobotDataset,
        "split_dataset": mock_split_dataset,
        "merge_datasets": mock_merge_datasets,
    }

    for key, old_val in saved.items():
        if old_val is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = old_val


# ------------------------------------------------------------------
# Job tracking
# ------------------------------------------------------------------


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


# ------------------------------------------------------------------
# split_dataset
# ------------------------------------------------------------------


class TestSplitDataset:
    @pytest.mark.asyncio
    async def test_split_returns_job_id(
        self, service: DatasetOpsService, derived_dir: Path, mock_lerobot: dict
    ) -> None:
        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)

            job_id = await service.split_dataset(
                source_path="/tmp/source-ds",
                episode_ids=[0, 1, 5],
                target_name="my-split",
            )
            assert isinstance(job_id, str)
            assert len(job_id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_split_runs_to_complete(
        self, service: DatasetOpsService, derived_dir: Path, mock_lerobot: dict
    ) -> None:
        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)

            job_id = await service.split_dataset(
                source_path="/tmp/source-ds",
                episode_ids=[0, 1, 5],
                target_name="split-test",
            )

            # Wait for the executor to finish
            await asyncio.sleep(0.5)

            job = service.get_job_status(job_id)
            assert job is not None
            assert job["status"] == "complete"
            assert job["error"] is None
            assert job["result_path"] == str(derived_dir / "split-test")

            # Check provenance was written
            prov_path = derived_dir / "split-test" / "provenance.json"
            assert prov_path.exists()
            prov = json.loads(prov_path.read_text())
            assert prov["operation"] == "split"
            assert prov["target_name"] == "split-test"
            assert prov["sources"][0]["episode_ids"] == [0, 1, 5]
            assert prov["lerobot_version"] == "3.0"

    @pytest.mark.asyncio
    async def test_split_failure_cleans_up(
        self, service: DatasetOpsService, derived_dir: Path, mock_lerobot: dict
    ) -> None:
        mock_lerobot["split_dataset"].side_effect = RuntimeError("split failed")

        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)

            job_id = await service.split_dataset(
                source_path="/tmp/source-ds",
                episode_ids=[0],
                target_name="fail-split",
            )

            await asyncio.sleep(0.5)

            job = service.get_job_status(job_id)
            assert job is not None
            assert job["status"] == "failed"
            assert "split failed" in job["error"]

            # Temp dir should be cleaned up
            remaining = [p for p in derived_dir.iterdir() if p.name.startswith(".split-")]
            assert len(remaining) == 0


# ------------------------------------------------------------------
# merge_datasets
# ------------------------------------------------------------------


class TestMergeDatasets:
    @pytest.mark.asyncio
    async def test_merge_runs_to_complete(
        self, service: DatasetOpsService, derived_dir: Path, mock_lerobot: dict
    ) -> None:
        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)

            job_id = await service.merge_datasets(
                source_paths=["/tmp/ds-a", "/tmp/ds-b"],
                target_name="merged-test",
            )

            await asyncio.sleep(0.5)

            job = service.get_job_status(job_id)
            assert job is not None
            assert job["status"] == "complete"
            assert job["result_path"] == str(derived_dir / "merged-test")

            prov_path = derived_dir / "merged-test" / "provenance.json"
            assert prov_path.exists()
            prov = json.loads(prov_path.read_text())
            assert prov["operation"] == "merge"
            assert len(prov["sources"]) == 2

    @pytest.mark.asyncio
    async def test_merge_failure_cleans_up(
        self, service: DatasetOpsService, derived_dir: Path, mock_lerobot: dict
    ) -> None:
        mock_lerobot["merge_datasets"].side_effect = RuntimeError("merge boom")

        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)

            job_id = await service.merge_datasets(
                source_paths=["/tmp/ds-a"],
                target_name="fail-merge",
            )

            await asyncio.sleep(0.5)

            job = service.get_job_status(job_id)
            assert job is not None
            assert job["status"] == "failed"
            assert "merge boom" in job["error"]

            remaining = [p for p in derived_dir.iterdir() if p.name.startswith(".merge-")]
            assert len(remaining) == 0


# ------------------------------------------------------------------
# list_derived_datasets / get_provenance
# ------------------------------------------------------------------


class TestListAndProvenance:
    def test_list_empty(self, service: DatasetOpsService, derived_dir: Path) -> None:
        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)
            result = service.list_derived_datasets()
            assert result == []

    def test_list_with_datasets(self, service: DatasetOpsService, derived_dir: Path) -> None:
        (derived_dir / "ds-a").mkdir()
        (derived_dir / "ds-b").mkdir()
        prov = {"operation": "split", "target_name": "ds-a"}
        (derived_dir / "ds-a" / "provenance.json").write_text(json.dumps(prov))

        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)
            result = service.list_derived_datasets()
            assert len(result) == 2
            assert result[0]["name"] == "ds-a"
            assert result[0]["provenance"]["operation"] == "split"
            assert result[1]["name"] == "ds-b"
            assert "provenance" not in result[1]

    def test_list_nonexistent_dir(self, service: DatasetOpsService, tmp_path: Path) -> None:
        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(tmp_path / "nope")
            result = service.list_derived_datasets()
            assert result == []

    def test_get_provenance_exists(self, service: DatasetOpsService, derived_dir: Path) -> None:
        ds_dir = derived_dir / "my-ds"
        ds_dir.mkdir()
        prov = {"operation": "merge", "target_name": "my-ds"}
        (ds_dir / "provenance.json").write_text(json.dumps(prov))

        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)
            result = service.get_provenance("my-ds")
            assert result is not None
            assert result["operation"] == "merge"

    def test_get_provenance_missing(self, service: DatasetOpsService, derived_dir: Path) -> None:
        with patch("backend.config.settings") as mock_settings:
            mock_settings.derived_dataset_path = str(derived_dir)
            result = service.get_provenance("nonexistent")
            assert result is None


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------


def test_singleton_import() -> None:
    from backend.services.dataset_ops_service import dataset_ops_service

    assert isinstance(dataset_ops_service, DatasetOpsService)
