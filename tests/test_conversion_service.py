import json
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Make sure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.conversion_service import ConversionService, ConversionJob


@pytest.fixture
def tmp_profiles(tmp_path):
    return tmp_path / "conversion_configs"


@pytest.fixture
def svc(tmp_profiles):
    tmp_profiles.mkdir()
    return ConversionService(profiles_dir=tmp_profiles)


def test_save_and_load_profile(svc, tmp_profiles):
    profile = {
        "input_path": "/bags",
        "repo_id": "psedulab/test",
        "output_path": "/mnt/hf/test",
        "task": "test_task",
        "fps": 20,
        "camera_topic_map": {},
        "joint_names": [],
        "state_topic": "/joint_states",
        "action_topics_map": {"leader": "/joint_states"},
        "task_instruction": [],
        "tags": [],
    }
    svc.save_profile("myprofile", profile)
    loaded = svc.load_profile("myprofile")
    assert loaded["task"] == "test_task"
    assert loaded["fps"] == 20


def test_list_profiles(svc):
    svc.save_profile("p1", {"task": "t1"})
    svc.save_profile("p2", {"task": "t2"})
    names = svc.list_profiles()
    assert "p1" in names
    assert "p2" in names


def test_delete_profile(svc):
    svc.save_profile("todel", {"task": "x"})
    svc.delete_profile("todel")
    assert "todel" not in svc.list_profiles()


def test_delete_nonexistent_profile_raises(svc):
    with pytest.raises(FileNotFoundError):
        svc.delete_profile("nope")


def test_initial_watch_state(svc):
    status = svc.get_watch_status()
    assert status["watching"] is False
    assert status["input_path"] is None


def test_job_list_initially_empty(svc):
    jobs = svc.get_jobs()
    assert jobs == []
