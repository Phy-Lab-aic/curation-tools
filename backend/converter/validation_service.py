"""Persistence helpers for converter validation state."""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from backend.converter.service import LEROBOT_BASE

ValidationMode = Literal["quick", "full"]
ValidationStatus = Literal["not_run", "running", "passed", "failed", "partial"]

VALIDATION_STATE_FILE = LEROBOT_BASE / "convert_validation_state.json"

_validation_locks: dict[tuple[str, ValidationMode], asyncio.Lock] = {}
_validation_locks_mutex = threading.Lock()
_state_write_lock = threading.Lock()


class ValidationAlreadyRunningError(RuntimeError):
    """Raised when a validation run is already active for a task/mode pair."""


@dataclass(slots=True)
class ValidationResult:
    status: ValidationStatus
    summary: str
    checked_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "summary": self.summary,
            "checked_at": self.checked_at,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lock_for(cell_task: str, mode: ValidationMode) -> asyncio.Lock:
    key = (cell_task, mode)
    with _validation_locks_mutex:
        lock = _validation_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _validation_locks[key] = lock
        return lock


def ensure_not_running(cell_task: str, mode: ValidationMode) -> None:
    if _lock_for(cell_task, mode).locked():
        raise ValidationAlreadyRunningError(
            f"Validation is already running for {cell_task!r} in {mode!r} mode."
        )


def read_validation_state() -> dict:
    try:
        if VALIDATION_STATE_FILE.is_file():
            return json.loads(VALIDATION_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def write_validation_state(state: dict) -> None:
    VALIDATION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = Path(f"{VALIDATION_STATE_FILE}.tmp")
    tmp_file.write_text(
        json.dumps(state, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_file.replace(VALIDATION_STATE_FILE)


def _upsert_result(
    state: dict,
    cell_task: str,
    mode: ValidationMode,
    result: ValidationResult,
) -> dict:
    task_state = state.setdefault(cell_task, {})
    task_state[mode] = result.as_dict()
    return state


def _persist_running_result(
    cell_task: str,
    mode: ValidationMode,
    result: ValidationResult,
) -> None:
    with _state_write_lock:
        state = read_validation_state()
        write_validation_state(_upsert_result(state, cell_task, mode, result))


async def mark_validation_running(
    cell_task: str,
    mode: ValidationMode,
) -> None:
    lock = _lock_for(cell_task, mode)
    ensure_not_running(cell_task, mode)
    await lock.acquire()
    try:
        result = ValidationResult(
            status="running",
            summary="Quick check running" if mode == "quick" else "Full check running",
            checked_at=_now_iso(),
        )
        await asyncio.to_thread(_persist_running_result, cell_task, mode, result)
    except Exception:
        lock.release()
        raise
