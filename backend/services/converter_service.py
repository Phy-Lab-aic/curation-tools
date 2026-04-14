"""Docker CLI wrapper for the rosbag-to-lerobot auto_converter."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
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

# Module-level flag set while `build_image` is running
_build_in_progress: bool = False

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


def _run(cmd: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """Run *cmd* synchronously and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -1, "", "command not found"

# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def check_docker() -> bool:
    """Return ``True`` if the Docker daemon is reachable."""
    rc, _, _ = _run(["docker", "info"], timeout=5.0)
    return rc == 0


def get_container_state() -> str:
    """Return the container state string (e.g. ``running``, ``exited``)."""
    rc, stdout, _ = _run(
        ["docker", "inspect", CONTAINER_NAME, "--format", "{{.State.Status}}"],
        timeout=5.0,
    )
    if rc == 0:
        return stdout.strip()
    return "stopped"


def get_status() -> ConverterStatus:
    """Combine docker check, container state, and progress into a status."""
    global _build_in_progress

    docker_ok = check_docker()
    if not docker_ok:
        return ConverterStatus(
            container_state="unknown",
            docker_available=False,
            summary="Docker is not available",
        )

    if _build_in_progress:
        return ConverterStatus(
            container_state="building",
            docker_available=True,
            summary="Image build in progress",
        )

    state = get_container_state()
    tasks: list[TaskProgress] = []
    summary = ""

    if state == "running":
        tasks, summary = parse_progress()

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
    global _build_in_progress
    _build_in_progress = True
    try:
        proc = await asyncio.create_subprocess_exec(
            *_compose_cmd("build", "--no-cache"),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert proc.stdout is not None
        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace").rstrip("\n")
            if on_line:
                on_line(line)
        await proc.wait()
        return proc.returncode or 0
    finally:
        _build_in_progress = False


def start_converter() -> tuple[bool, str]:
    """Clean up old container and start a fresh one. Returns (ok, message)."""
    # Remove old container if it exists
    _run(["docker", "rm", "-f", CONTAINER_NAME], timeout=10.0)

    cmd = _compose_cmd(
        "run", "-d",
        "--name", CONTAINER_NAME,
        "convert-server",
        "python3", "/app/auto_converter.py",
    )
    rc, stdout, stderr = _run(cmd, timeout=30.0)
    if rc == 0:
        return True, stdout.strip() or "started"
    return False, stderr.strip() or "failed to start"


def stop_converter() -> tuple[bool, str]:
    """Stop and remove the converter stack. Returns (ok, message)."""
    rc, stdout, stderr = _run(_compose_cmd("down"), timeout=30.0)
    if rc == 0:
        return True, stdout.strip() or "stopped"
    return False, stderr.strip() or "failed to stop"


def parse_progress() -> tuple[list[TaskProgress], str]:
    """Parse the last scan table from container logs.

    Returns (list_of_task_progress, summary_line).
    """
    rc, stdout, stderr = _run(
        ["docker", "logs", "--tail", "100", CONTAINER_NAME],
        timeout=10.0,
    )
    output = stdout + stderr  # docker logs may write to stderr
    if rc != 0 or not output:
        return [], ""

    # Find the last scan table block bounded by ━ lines
    lines = output.splitlines()
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
        m = _ROW_RE.match(line)
        if m:
            tasks.append(TaskProgress(
                cell_task=m.group(1).strip(),
                total=int(m.group(2)),
                done=int(m.group(3)),
                pending=int(m.group(4)),
                failed=int(m.group(5)),
                retry=int(m.group(6)),
            ))

    # Look for the Total summary line after the table
    for line in lines[block_end:]:
        m = _TOTAL_RE.search(line)
        if m:
            summary = line.strip()
            break

    return tasks, summary


async def stream_logs(tail: int = 200) -> AsyncGenerator[str, None]:
    """Async generator that streams container logs, yielding lines."""
    proc = await asyncio.create_subprocess_exec(
        "docker", "logs", "-f", "--tail", str(tail), CONTAINER_NAME,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    try:
        async for raw_line in proc.stdout:
            yield raw_line.decode(errors="replace").rstrip("\n")
    finally:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
