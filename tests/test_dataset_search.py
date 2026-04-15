"""Tests for GET /api/datasets/search — cross-dataset search via SQLite."""

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


from backend.core.db import get_db, init_db, close_db, _reset
from backend.main import app


@pytest_asyncio.fixture(autouse=True)
async def tmp_db(monkeypatch):
    _reset()  # clear any stale connection from prior tests
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    await init_db()
    db = await get_db()
    for i, (name, cell, robot, fps, episodes) in enumerate([
        ("ds_good", "cell_a", "so100", 30, 100),
        ("ds_mixed", "cell_a", "so100", 30, 50),
        ("ds_small", "cell_b", "koch", 60, 5),
    ], start=1):
        await db.execute(
            "INSERT INTO datasets (id, path, name, cell_name, robot_type, fps, total_episodes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (i, f"/mnt/nas/{cell}/{name}", name, cell, robot, fps, episodes),
        )
        good = {1: 80, 2: 20, 3: 3}[i]
        normal = {1: 10, 2: 10, 3: 1}[i]
        bad = {1: 10, 2: 20, 3: 1}[i]
        await db.execute(
            "INSERT INTO dataset_stats (dataset_id, graded_count, good_count, normal_count, bad_count) VALUES (?, ?, ?, ?, ?)",
            (i, good + normal + bad, good, normal, bad),
        )
    await db.commit()
    yield tmp
    await close_db()
    _reset()
    tmp.unlink(missing_ok=True)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestDatasetSearch:
    @pytest.mark.asyncio
    async def test_no_filters_returns_all(self, client):
        resp = await client.get("/api/datasets/search")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    @pytest.mark.asyncio
    async def test_filter_by_robot_type(self, client):
        resp = await client.get("/api/datasets/search?robot_type=so100")
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()]
        assert "ds_good" in names
        assert "ds_mixed" in names
        assert "ds_small" not in names

    @pytest.mark.asyncio
    async def test_filter_by_cell(self, client):
        resp = await client.get("/api/datasets/search?cell=cell_b")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "ds_small"

    @pytest.mark.asyncio
    async def test_filter_by_min_good_ratio(self, client):
        resp = await client.get("/api/datasets/search?min_good_ratio=0.7")
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()]
        assert "ds_good" in names  # 80/100 = 0.8
        assert "ds_mixed" not in names  # 20/50 = 0.4

    @pytest.mark.asyncio
    async def test_filter_by_min_episodes(self, client):
        resp = await client.get("/api/datasets/search?min_episodes=10")
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()]
        assert "ds_small" not in names

    @pytest.mark.asyncio
    async def test_combined_filters(self, client):
        resp = await client.get("/api/datasets/search?robot_type=so100&min_good_ratio=0.5")
        assert resp.status_code == 200
        names = [d["name"] for d in resp.json()]
        assert names == ["ds_good"]
