"""Tests for converter progress and container status logic."""

from unittest.mock import AsyncMock, call, patch

import pytest

import backend.converter.service as svc

from backend.converter.service import (
    ContainerStateInfo,
    TaskProgress,
    build_progress,
    get_status,
    start_converter,
)


class TestBuildProgress:
    def test_uses_actual_output_when_state_overreports(self):
        with patch(
            "backend.converter.service.scan_raw_totals",
            return_value={"cell005/Amore_dualpick/spray_clean": 216},
        ), patch(
            "backend.converter.service.read_state",
            return_value={
                "cell005/Amore_dualpick/spray_clean": {
                    "converted_count": 216,
                    "failed_serials": [],
                    "transient_failed": {"retry-me": {}},
                },
            },
        ), patch(
            "backend.converter.service._count_output_episodes",
            return_value=170,
        ):
            tasks, summary = build_progress()

        assert tasks == [
            TaskProgress(
                "cell005/Amore_dualpick/spray_clean",
                216,
                170,
                46,
                0,
                1,
            ),
        ]
        assert summary == "1 tasks | 216 recordings | 170 done | 46 pending | 0 failed"

    def test_falls_back_to_state_when_output_is_unavailable(self):
        with patch(
            "backend.converter.service.scan_raw_totals",
            return_value={"cell001/task_a": 10},
        ), patch(
            "backend.converter.service.read_state",
            return_value={
                "cell001/task_a": {
                    "converted_count": 4,
                    "failed_serials": ["s1"],
                    "transient_failed": {},
                },
            },
        ), patch(
            "backend.converter.service._count_output_episodes",
            return_value=None,
        ):
            tasks, summary = build_progress()

        assert tasks == [TaskProgress("cell001/task_a", 10, 4, 5, 1, 0)]
        assert summary == "1 tasks | 10 recordings | 4 done | 5 pending | 1 failed"


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_docker_unavailable(self):
        with patch("backend.converter.service.check_docker", new_callable=AsyncMock, return_value=False):
            status = await get_status()

        assert status.docker_available is False
        assert status.container_state == "unknown"

    @pytest.mark.asyncio
    async def test_stopped_container_uses_progress_snapshot(self):
        fake_tasks = [TaskProgress("a/b", 10, 5, 3, 2, 0)]
        with patch("backend.converter.service.check_docker", new_callable=AsyncMock, return_value=True), patch(
            "backend.converter.service.get_container_state_info",
            new_callable=AsyncMock,
            return_value=ContainerStateInfo(status="stopped"),
        ), patch(
            "backend.converter.service.build_progress",
            return_value=(fake_tasks, "Total: 1 task"),
        ):
            status = await get_status()

        assert status.docker_available is True
        assert status.container_state == "stopped"
        assert status.tasks == fake_tasks

    @pytest.mark.asyncio
    async def test_building_state(self):
        import backend.converter.service as svc

        await svc._build_lock.acquire()
        try:
            with patch("backend.converter.service.check_docker", new_callable=AsyncMock, return_value=True):
                status = await get_status()
            assert status.container_state == "building"
        finally:
            svc._build_lock.release()


class TestStartConverter:
    @pytest.mark.asyncio
    async def test_allows_dead_container_to_restart(self):
        run_mock = AsyncMock(side_effect=[
            (0, "", ""),
            (0, "started", ""),
        ])

        with patch("backend.converter.service.get_container_state", new_callable=AsyncMock, return_value="dead"), patch(
            "backend.converter.service._run",
            run_mock,
        ), patch(
            "backend.converter.service._compose_cmd",
            side_effect=lambda *args: ["docker", "compose", *args],
        ):
            ok, msg = await start_converter()

        assert ok is True
        assert msg == "started"
        assert run_mock.await_args_list == [
            call(["docker", "rm", "-f", svc.CONTAINER_NAME], timeout=10.0),
            call(["docker", "compose", "run", "-d", "--build", "--name", svc.CONTAINER_NAME, "convert-server", "python3", "/app/auto_converter.py"], timeout=30.0),
        ]


class TestContainerStateHelpers:
    def test_parse_container_state_returns_stopped_for_malformed_json(self):
        info = svc._parse_container_state("{not-json}")

        assert info == ContainerStateInfo(status="stopped")

    def test_parse_container_state_returns_stopped_for_non_object_json(self):
        info = svc._parse_container_state('["running"]')

        assert info == ContainerStateInfo(status="stopped")
