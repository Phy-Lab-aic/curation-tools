"""Docker CLI wrapper for the rosbag-to-lerobot auto_converter."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator, Callable

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROSBAG_PROJECT = Path(os.environ.get(
    "CONVERTER_PROJECT_PATH",
    "/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot",
))
COMPOSE_FILE = ROSBAG_PROJECT / "docker" / "docker-compose.yml"
PROJECT_NAME = "convert-server"
CONTAINER_NAME = "convert-server"

# Module-level lock to guard concurrent build requests
_build_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TaskProgress:
    cell_task: str
    total: int
    done: int
    pending: int
    failed: int
    retry: int


@dataclass
class ConverterStatus:
    container_state: str
    docker_available: bool
    tasks: list[TaskProgress] = field(default_factory=list)
    summary: str = ""

# ---------------------------------------------------------------------------
# Regex patterns for progress parsing
# ---------------------------------------------------------------------------

_ROW_RE = re.compile(
    r"^\s+(.{1,36})\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$"
)
_TOTAL_RE = re.compile(
    r"Total:\s+(\d+)\s+tasks?\s*\|\s*(\d+)\s+recordings?\s*\|\s*(\d+)\s+done"
    r"\s*\|\s*(\d+)\s+pending\s*\|\s*(\d+)\s+failed"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compose_cmd(*args: str) -> list[str]:
    """Build a ``docker compose`` command list."""
    return [
        "docker", "compose",
        "-p", PROJECT_NAME,
        "-f", str(COMPOSE_FILE),
        *args,
    ]


async def _run(cmd: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """Run *cmd* asynchronously and return (returncode, stdout, stderr)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return -1, "", "command not found"
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", "timeout"
    return proc.returncode or 0, stdout.decode(), stderr.decode()

# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


async def check_docker() -> bool:
    """Return ``True`` if the Docker daemon is reachable."""
    rc, _, _ = await _run(["docker", "info"], timeout=5.0)
    return rc == 0


async def get_container_state() -> str:
    """Return the container state string (e.g. ``running``, ``exited``)."""
    rc, stdout, _ = await _run(
        ["docker", "inspect", CONTAINER_NAME, "--format", "{{.State.Status}}"],
        timeout=5.0,
    )
    if rc == 0:
        return stdout.strip()
    return "stopped"


async def get_status() -> ConverterStatus:
    """Combine docker check, container state, and progress into a status."""
    docker_ok = await check_docker()
    if not docker_ok:
        return ConverterStatus(
            container_state="unknown",
            docker_available=False,
            summary="Docker is not available",
        )

    if _build_lock.locked():
        return ConverterStatus(
            container_state="building",
            docker_available=True,
            summary="Image build in progress",
        )

    state = await get_container_state()
    tasks: list[TaskProgress] = []
    summary = ""

    if state == "running":
        tasks, summary = await parse_progress()

    return ConverterStatus(
        container_state=state,
        docker_available=True,
        tasks=tasks,
        summary=summary,
    )


async def build_image(on_line: Callable[[str], None] | None = None) -> int:
    """Run ``docker compose build --no-cache``, streaming output via *on_line*.

    Returns the process exit code.
    """
    if _build_lock.locked():
        raise RuntimeError("Build already in progress")
    async with _build_lock:
        proc = await asyncio.create_subprocess_exec(
            *_compose_cmd("build", "--no-cache"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if proc.stdout is None:
            raise RuntimeError("Failed to capture build output")
        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace").rstrip("\n")
            if on_line:
                on_line(line)
        await proc.wait()
        return proc.returncode or 0


async def start_converter() -> tuple[bool, str]:
    """Clean up old container and start a fresh one. Returns (ok, message)."""
    # Remove old container if it exists
    await _run(["docker", "rm", "-f", CONTAINER_NAME], timeout=10.0)

    cmd = _compose_cmd(
        "run", "-d",
        "--name", CONTAINER_NAME,
        "convert-server",
        "python3", "/app/auto_converter.py",
    )
    rc, stdout, stderr = await _run(cmd, timeout=30.0)
    if rc == 0:
        return True, stdout.strip() or "started"
    return False, stderr.strip() or "failed to start"


async def stop_converter() -> tuple[bool, str]:
    """Stop and remove the converter stack. Returns (ok, message)."""
    rc, stdout, stderr = await _run(_compose_cmd("down"), timeout=30.0)
    if rc == 0:
        return True, stdout.strip() or "stopped"
    return False, stderr.strip() or "failed to stop"


async def parse_progress() -> tuple[list[TaskProgress], str]:
    """Parse the last scan table from container logs.

    Returns (list_of_task_progress, summary_line).
    """
    rc, stdout, stderr = await _run(
        ["docker", "logs", "--tail", "100", CONTAINER_NAME],
        timeout=10.0,
    )
    output = stdout + stderr  # docker logs may write to stderr
    if rc != 0 or not output:
        return [], ""

    # Strip timestamp + [LEVEL] prefix from each line
    # e.g. "2026-04-15 10:23:01 [INFO]   cell_a/task_1  ..." → "  cell_a/task_1  ..."
    raw_lines = output.splitlines()
    lines: list[str] = []
    for raw in raw_lines:
        idx = raw.find("]")
        if idx != -1 and "[" in raw[:idx]:
            lines.append(raw[idx + 1:])
        else:
            lines.append(raw)

    # Find the last scan table block bounded by ━ lines
    block_start: int | None = None
    block_end: int | None = None
    for i, line in enumerate(lines):
        if "━" in line:
            if block_start is None:
                block_start = i
                block_end = None
            else:
                block_end = i

    if block_start is None or block_end is None:
        return [], ""

    tasks: list[TaskProgress] = []
    summary = ""

    for line in lines[block_start:block_end + 1]:
        row_m = _ROW_RE.match(line)
        if row_m:
            tasks.append(TaskProgress(
                cell_task=row_m.group(1).strip(),
                total=int(row_m.group(2)),
                done=int(row_m.group(3)),
                pending=int(row_m.group(4)),
                failed=int(row_m.group(5)),
                retry=int(row_m.group(6)),
            ))

        total_m = _TOTAL_RE.search(line)
        if total_m:
            summary = line.strip()

    return tasks, summary


async def stream_logs(tail: int = 200) -> AsyncGenerator[str, None]:
    """Async generator that streams container logs, yielding lines."""
    proc = await asyncio.create_subprocess_exec(
        "docker", "logs", "-f", "--tail", str(tail), CONTAINER_NAME,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    if proc.stdout is None:
        raise RuntimeError("Failed to capture log output")
    try:
        async for raw_line in proc.stdout:
            yield raw_line.decode(errors="replace").rstrip("\n")
    finally:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
