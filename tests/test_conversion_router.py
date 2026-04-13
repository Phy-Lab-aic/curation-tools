import json
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.routers.conversion import router, get_conversion_service
from backend.services.conversion_service import ConversionService


@pytest.fixture
def tmp_svc(tmp_path):
    svc = ConversionService(profiles_dir=tmp_path / "profiles")
    return svc


@pytest.fixture
def client(tmp_svc):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_conversion_service] = lambda: tmp_svc
    return TestClient(app)


def test_list_profiles_empty(client):
    r = client.get("/api/conversion/configs")
    assert r.status_code == 200
    assert r.json() == []


def test_create_and_get_profile(client):
    payload = {
        "name": "myprofile",
        "config": {"task": "test", "fps": 20, "input_path": "/bags",
                   "output_path": "/mnt/out", "repo_id": "org/repo",
                   "camera_topic_map": {}, "joint_names": [],
                   "state_topic": "/js", "action_topics_map": {},
                   "task_instruction": [], "tags": []},
    }
    r = client.post("/api/conversion/configs", json=payload)
    assert r.status_code == 201

    r2 = client.get("/api/conversion/configs/myprofile")
    assert r2.status_code == 200
    assert r2.json()["task"] == "test"


def test_delete_profile(client):
    client.post("/api/conversion/configs",
                json={"name": "todel", "config": {"task": "x"}})
    r = client.delete("/api/conversion/configs/todel")
    assert r.status_code == 204

    r2 = client.get("/api/conversion/configs/todel")
    assert r2.status_code == 404


def test_watch_status_initial(client):
    r = client.get("/api/conversion/watch/status")
    assert r.status_code == 200
    assert r.json()["watching"] is False


def test_get_jobs_empty(client):
    r = client.get("/api/conversion/jobs")
    assert r.status_code == 200
    assert r.json() == []
