import asyncio
import threading
import time
from pathlib import Path
from unittest.mock import ANY

import pytest

import backend.converter.validation_service as validation_service
from backend.converter.validation_service import (
    ValidationAlreadyRunningError,
    ensure_not_running,
    mark_validation_running,
    read_validation_state,
    write_validation_state,
)


@pytest.fixture(autouse=True)
def isolated_validation_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state_file = tmp_path / "convert_validation_state.json"
    monkeypatch.setattr(
        "backend.converter.validation_service.VALIDATION_STATE_FILE",
        state_file,
    )
    validation_service._validation_locks.clear()
    monkeypatch.setattr(
        validation_service,
        "_validation_locks_mutex",
        threading.Lock(),
    )
    monkeypatch.setattr(
        validation_service,
        "_state_write_lock",
        threading.Lock(),
    )
    return state_file


class TestValidationStatePersistence:
    def test_read_validation_state_returns_empty_when_file_missing(self):
        assert read_validation_state() == {}

    def test_write_validation_state_round_trip(self):
        state = {
            "cell001/task_a": {
                "quick": {
                    "status": "passed",
                    "summary": "all good",
                    "checked_at": "2026-04-18T00:00:00+00:00",
                },
            },
        }

        write_validation_state(state)

        assert read_validation_state() == state

    @pytest.mark.asyncio
    async def test_mark_validation_running_persists_running_status_and_summary(self):
        result = await mark_validation_running("cell001/task_a", "quick")

        assert result is None

        assert read_validation_state() == {
            "cell001/task_a": {
                "quick": {
                    "status": "running",
                    "summary": "Quick check running",
                    "checked_at": ANY,
                },
            },
        }

    @pytest.mark.asyncio
    async def test_ensure_not_running_raises_when_same_lock_is_held(self):
        await mark_validation_running("cell001/task_a", "full")

        with pytest.raises(ValidationAlreadyRunningError):
            ensure_not_running("cell001/task_a", "full")

    @pytest.mark.asyncio
    async def test_concurrent_writes_preserve_both_task_entries(self, monkeypatch: pytest.MonkeyPatch):
        original_write = validation_service.write_validation_state

        def slow_write(state: dict) -> None:
            time.sleep(0.02)
            original_write(state)

        monkeypatch.setattr(validation_service, "write_validation_state", slow_write)

        await asyncio.gather(
            mark_validation_running("cell001/task_a", "quick"),
            mark_validation_running("cell002/task_b", "full"),
        )

        assert read_validation_state() == {
            "cell001/task_a": {
                "quick": {
                    "status": "running",
                    "summary": "Quick check running",
                    "checked_at": ANY,
                },
            },
            "cell002/task_b": {
                "full": {
                    "status": "running",
                    "summary": "Full check running",
                    "checked_at": ANY,
                },
            },
        }

    @pytest.mark.asyncio
    async def test_same_key_contention_allows_one_start_and_rejects_second(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        original_persist = validation_service._persist_running_result

        def slow_persist(cell_task: str, mode: str, result) -> None:
            time.sleep(0.02)
            original_persist(cell_task, mode, result)

        monkeypatch.setattr(validation_service, "_persist_running_result", slow_persist)

        first_task = asyncio.create_task(mark_validation_running("cell001/task_a", "quick"))
        await asyncio.sleep(0)
        second_task = asyncio.create_task(mark_validation_running("cell001/task_a", "quick"))

        first_result, second_result = await asyncio.gather(
            first_task,
            second_task,
            return_exceptions=True,
        )

        assert first_result is None
        assert isinstance(second_result, ValidationAlreadyRunningError)

    @pytest.mark.asyncio
    async def test_persistence_failure_releases_lock(self, monkeypatch: pytest.MonkeyPatch):
        def failing_persist(cell_task: str, mode: str, result) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(validation_service, "_persist_running_result", failing_persist)

        with pytest.raises(OSError, match="disk full"):
            await mark_validation_running("cell001/task_a", "quick")

        assert validation_service._lock_for("cell001/task_a", "quick").locked() is False
        ensure_not_running("cell001/task_a", "quick")

    def test_lock_for_returns_single_lock_under_threaded_same_key_first_access(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        original_lock_factory = validation_service.asyncio.Lock
        creation_barrier = threading.Barrier(2)
        start_barrier = threading.Barrier(3)
        created_locks: list[asyncio.Lock] = []
        returned_locks: list[asyncio.Lock] = []

        def slow_lock_factory() -> asyncio.Lock:
            try:
                creation_barrier.wait(timeout=0.1)
            except threading.BrokenBarrierError:
                pass
            lock = original_lock_factory()
            created_locks.append(lock)
            return lock

        def worker() -> None:
            start_barrier.wait(timeout=1)
            returned_locks.append(validation_service._lock_for("cell001/task_a", "quick"))

        monkeypatch.setattr(validation_service.asyncio, "Lock", slow_lock_factory)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        start_barrier.wait(timeout=1)
        for thread in threads:
            thread.join(timeout=1)

        assert len(created_locks) == 1
        assert len(returned_locks) == 2
        assert returned_locks[0] is returned_locks[1]
        assert returned_locks[0] is created_locks[0]
