import json
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.core.config import settings

_FRONTEND_ASSETS = Path(__file__).resolve().parents[1] / "frontend" / "dist" / "assets"
_FRONTEND_ASSETS.mkdir(parents=True, exist_ok=True)

from backend.main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def configured_sources(tmp_path, monkeypatch):
    base = tmp_path / "data_div" / "2026_1"
    source_a = base / "lerobot"
    source_b = base / "lerobot_test"
    ignored = base / "not_registered"

    for source, cell_names in (
        (source_a, ("cell001", "cell002")),
        (source_b, ("cell101",)),
        (ignored, ("cell999",)),
    ):
        for cell_name in cell_names:
            meta = source / cell_name / "dataset_a" / "meta"
            meta.mkdir(parents=True)
            (meta / "info.json").write_text(
                json.dumps(
                    {
                        "fps": 30,
                        "total_episodes": 10,
                        "robot_type": "ur5e",
                        "features": {},
                        "total_tasks": 1,
                    }
                ),
                encoding="utf-8",
            )

    monkeypatch.setattr(settings, "dataset_root_base", str(base), raising=False)
    monkeypatch.setattr(settings, "dataset_sources", ["lerobot", "lerobot_test"], raising=False)
    monkeypatch.setattr(settings, "allowed_dataset_roots", [str(source_a), str(source_b)])

    return {
        "base": base,
        "lerobot": source_a,
        "lerobot_test": source_b,
    }


class TestCellsAPI:
    @pytest.mark.asyncio
    async def test_list_sources_returns_only_registered_sources(self, client, configured_sources):
        resp = await client.get("/api/cells/sources")

        assert resp.status_code == 200
        payload = resp.json()
        assert [item["name"] for item in payload] == ["lerobot", "lerobot_test"]
        assert [item["cell_count"] for item in payload] == [2, 1]
        assert [item["path"] for item in payload] == [
            str(configured_sources["lerobot"].resolve()),
            str(configured_sources["lerobot_test"].resolve()),
        ]

    @pytest.mark.asyncio
    async def test_list_cells_filters_to_requested_root(self, client, configured_sources):
        resp = await client.get("/api/cells", params={"root": str(configured_sources["lerobot_test"])})

        assert resp.status_code == 200
        payload = resp.json()
        assert [item["name"] for item in payload] == ["cell101"]
        assert payload[0]["mount_root"] == str(configured_sources["lerobot_test"].resolve())
