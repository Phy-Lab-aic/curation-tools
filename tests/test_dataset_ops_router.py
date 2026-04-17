"""Tests for Dataset Ops API router — mocks dataset_ops_service methods."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent))

_frontend_assets = Path(__file__).parent.parent / "frontend" / "dist" / "assets"
_frontend_assets.mkdir(parents=True, exist_ok=True)

from backend.config import settings
from backend.main import app
from backend.services.dataset_ops_service import dataset_ops_service

_orig_roots = list(settings.allowed_dataset_roots)


@pytest.fixture(autouse=True)
def _allow_tmp_paths(tmp_path):
    """Allow tmp_path in dataset root validation for tests."""
    settings.allowed_dataset_roots = _orig_roots + [str(tmp_path), "/nonexistent"]
    yield
    settings.allowed_dataset_roots = _orig_roots


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# POST /api/datasets/split
# ---------------------------------------------------------------------------


class TestSplitDataset:
    @pytest.mark.asyncio
    async def test_split_returns_202_with_job(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()
        source_path = f"{source.parent}/./{source.name}"

        with patch.object(
            dataset_ops_service,
            "split_dataset",
            new_callable=AsyncMock,
            return_value="abc-123",
        ) as split_dataset:
            resp = await client.post(
                "/api/datasets/split",
                json={
                    "source_path": source_path,
                    "episode_ids": [0, 1, 5],
                    "target_name": "my-split",
                },
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["job_id"] == "abc-123"
        assert data["operation"] == "split"
        assert data["status"] == "queued"
        split_dataset.assert_awaited_once_with(
            source_path=str(source.resolve()),
            episode_ids=[0, 1, 5],
            target_name="my-split",
            output_dir=None,
        )

    @pytest.mark.asyncio
    async def test_split_400_if_output_dir_outside_allowed_roots(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()

        with patch.object(
            dataset_ops_service,
            "split_dataset",
            new_callable=AsyncMock,
        ) as split_dataset:
            resp = await client.post(
                "/api/datasets/split",
                json={
                    "source_path": str(source),
                    "episode_ids": [0],
                    "target_name": "new-split",
                    "output_dir": "/etc",
                },
            )

        assert resp.status_code == 400
        assert "allowed roots" in resp.json()["detail"]
        split_dataset.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_split_404_if_source_missing(self, client):
        resp = await client.post(
            "/api/datasets/split",
            json={
                "source_path": "/nonexistent/path",
                "episode_ids": [0],
                "target_name": "new-split",
            },
        )
        assert resp.status_code == 404
        assert "Source path not found" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_split_422_if_episode_ids_empty(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()

        resp = await client.post(
            "/api/datasets/split",
            json={
                "source_path": str(source),
                "episode_ids": [],
                "target_name": "new-split",
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/datasets/split-into
# ---------------------------------------------------------------------------


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
        data = resp.json()
        assert data["job_id"] == "sync-job-1"
        assert data["operation"] == "sync_good_episodes"
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
    async def test_split_into_404_source_missing(self, client):
        resp = await client.post(
            "/api/datasets/split-into",
            json={
                "source_path": "/nonexistent/source",
                "episode_ids": [0],
                "destination_path": "/nonexistent/target",
            },
        )
        assert resp.status_code == 404
        assert "Source path not found" in resp.json()["detail"]

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

    @pytest.mark.asyncio
    async def test_split_into_422_empty_episodes(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()

        resp = await client.post(
            "/api/datasets/split-into",
            json={
                "source_path": str(source),
                "episode_ids": [],
                "destination_path": str(tmp_path / "good-sync"),
            },
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/datasets/merge
# ---------------------------------------------------------------------------


class TestMergeDatasets:
    @pytest.mark.asyncio
    async def test_merge_returns_202_with_job(self, client, tmp_path):
        src_a = tmp_path / "ds-a"
        src_b = tmp_path / "ds-b"
        src_a.mkdir()
        src_b.mkdir()
        source_paths = [f"{src_a.parent}/./{src_a.name}", f"{src_b.parent}/./{src_b.name}"]

        with patch.object(
            dataset_ops_service,
            "merge_datasets",
            new_callable=AsyncMock,
            return_value="merge-job-999",
        ) as merge_datasets:
            resp = await client.post(
                "/api/datasets/merge",
                json={
                    "source_paths": source_paths,
                    "target_name": "merged-out",
                },
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["job_id"] == "merge-job-999"
        assert data["operation"] == "merge"
        assert data["status"] == "queued"
        merge_datasets.assert_awaited_once_with(
            source_paths=[str(src_a.resolve()), str(src_b.resolve())],
            target_name="merged-out",
            output_dir=None,
        )

    @pytest.mark.asyncio
    async def test_merge_404_if_source_missing(self, client, tmp_path):
        existing = tmp_path / "ds-a"
        existing.mkdir()

        resp = await client.post(
            "/api/datasets/merge",
            json={
                "source_paths": [str(existing), "/nonexistent/ds-b"],
                "target_name": "merged-out",
            },
        )
        assert resp.status_code == 404
        assert "Source path not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /api/datasets/delete
# ---------------------------------------------------------------------------


class TestDeleteEpisodes:
    @pytest.mark.asyncio
    async def test_delete_returns_202_with_canonical_paths(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()
        source_path = f"{source.parent}/./{source.name}"

        with patch.object(
            dataset_ops_service,
            "delete_episodes",
            new_callable=AsyncMock,
            return_value="delete-job-123",
        ) as delete_episodes:
            resp = await client.post(
                "/api/datasets/delete",
                json={
                    "source_path": source_path,
                    "episode_ids": [2, 4],
                },
            )

        assert resp.status_code == 202
        assert resp.json() == {
            "job_id": "delete-job-123",
            "operation": "delete",
            "status": "queued",
        }
        delete_episodes.assert_awaited_once_with(
            source_path=str(source.resolve()),
            episode_ids=[2, 4],
            output_dir=None,
        )


# ---------------------------------------------------------------------------
# POST /api/datasets/stamp-cycles
# ---------------------------------------------------------------------------


class TestStampCycles:
    @pytest.mark.asyncio
    async def test_returns_202_with_job(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()

        with patch.object(
            dataset_ops_service,
            "stamp_cycles",
            new_callable=AsyncMock,
            return_value="xyz-789",
        ) as stamp_cycles:
            resp = await client.post(
                "/api/datasets/stamp-cycles",
                json={
                    "source_path": str(source),
                    "overwrite": False,
                },
            )

        assert resp.status_code == 202
        assert resp.json() == {
            "job_id": "xyz-789",
            "operation": "stamp_cycles",
            "status": "queued",
        }
        stamp_cycles.assert_awaited_once_with(
            source_path=str(source.resolve()),
            overwrite=False,
        )

    @pytest.mark.asyncio
    async def test_404_if_source_missing(self, client):
        resp = await client.post(
            "/api/datasets/stamp-cycles",
            json={
                "source_path": "/nonexistent/missing-ds",
                "overwrite": False,
            },
        )

        assert resp.status_code == 404
        assert "Source path not found" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_rejects_path_outside_allowed_roots(self, client):
        resp = await client.post(
            "/api/datasets/stamp-cycles",
            json={
                "source_path": "/etc",
                "overwrite": False,
            },
        )

        assert resp.status_code == 400
        assert "allowed roots" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/datasets/stamp-cycles/status
# ---------------------------------------------------------------------------


class TestStampCyclesStatus:
    @pytest.mark.asyncio
    async def test_status_returns_describe(self, client, tmp_path):
        source = tmp_path / "source-ds"
        source.mkdir()
        payload = {
            "stamped": True,
            "is_terminal_count_sample": 4,
            "unexpected": "ignored-by-response-model",
        }

        with patch(
            "backend.datasets.routers.dataset_ops.describe_stamp_state",
            return_value=payload,
        ) as describe:
            resp = await client.get(
                "/api/datasets/stamp-cycles/status",
                params={"path": str(source)},
            )

        assert resp.status_code == 200
        assert resp.json() == {
            "stamped": True,
            "is_terminal_count_sample": 4,
        }
        describe.assert_called_once_with(source)

    @pytest.mark.asyncio
    async def test_status_400_if_path_outside_allowed_roots(self, client):
        resp = await client.get(
            "/api/datasets/stamp-cycles/status",
            params={"path": "/etc"},
        )

        assert resp.status_code == 400
        assert "allowed roots" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_status_404_if_path_missing(self, client):
        resp = await client.get(
            "/api/datasets/stamp-cycles/status",
            params={"path": "/nonexistent/missing-ds"},
        )

        assert resp.status_code == 404
        assert "Source path not found" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /api/datasets/ops/status/{job_id}
# ---------------------------------------------------------------------------


class TestGetJobStatus:
    @pytest.mark.asyncio
    async def test_returns_job_status(self, client):
        job = {
            "id": "job-abc",
            "operation": "sync_good_episodes",
            "status": "complete",
            "created_at": "2024-01-01T00:00:00+00:00",
            "completed_at": "2024-01-01T00:01:00+00:00",
            "error": None,
            "result_path": "/tmp/derived/my-split",
            "summary": {"mode": "merge", "created": 2, "skipped_duplicates": 1},
        }
        with patch.object(dataset_ops_service, "get_job_status", return_value=job):
            resp = await client.get("/api/datasets/ops/status/job-abc")

        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "job-abc"
        assert data["operation"] == "sync_good_episodes"
        assert data["status"] == "complete"
        assert data["completed_at"] == "2024-01-01T00:01:00+00:00"
        assert data["result_path"] == "/tmp/derived/my-split"
        assert data["error"] is None
        assert data["summary"] == {"mode": "merge", "created": 2, "skipped_duplicates": 1}

    @pytest.mark.asyncio
    async def test_returns_queued_job(self, client):
        job = {
            "id": "job-xyz",
            "operation": "merge",
            "status": "queued",
            "created_at": "2024-01-01T00:00:00+00:00",
            "completed_at": None,
            "error": None,
            "result_path": None,
        }
        with patch.object(dataset_ops_service, "get_job_status", return_value=job):
            resp = await client.get("/api/datasets/ops/status/job-xyz")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert data["completed_at"] is None
        assert data["result_path"] is None

    @pytest.mark.asyncio
    async def test_returns_404_if_job_missing(self, client):
        with patch.object(dataset_ops_service, "get_job_status", return_value=None):
            resp = await client.get("/api/datasets/ops/status/nonexistent-job")

        assert resp.status_code == 404
        assert "Job not found" in resp.json()["detail"]
