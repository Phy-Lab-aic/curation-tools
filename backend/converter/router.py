"""Converter control API — build/start/stop + status/progress."""

import asyncio
import json
import logging
import re

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.converter import service as converter_service

# ---------------------------------------------------------------------------
# Log line parser — extracts structured events from raw container output
# ---------------------------------------------------------------------------

_NOISE_RE = re.compile(
    r"^(_read_rosbag|Traceback |  File |    |ValueError|^$)"
)
_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[(\w+)]\s*(.*)"
)
_CONVERTED_RE = re.compile(
    r"Converted:\s+(.+?)\s+\((\d+)\s+frames,\s+([\d.]+)s\)"
)
_FAILED_RE = re.compile(
    r"Failed\s+\[(\w+)]:\s+(.+?):\s+(.*)"
)
_CONVERTING_RE = re.compile(
    r"Converting\s+(.+?):\s+(\d+)\s+new recordings"
)
_SCAN_RE = re.compile(
    r"(\d+)\s+tasks?\s+with\s+(\d+)\s+pending"
)


def _parse_log_line(raw: str) -> dict | None:
    """Parse a raw log line into a structured event dict, or None to skip."""
    if not raw.strip() or _NOISE_RE.match(raw):
        return None
    # Indented continuation lines (quality anomaly details)
    if raw.startswith("  ") or raw.startswith("Timestamp gap"):
        return None

    ts_m = _TS_RE.match(raw)
    if not ts_m:
        return None

    ts, level, msg = ts_m.group(1), ts_m.group(2), ts_m.group(3).strip()

    conv_m = _CONVERTED_RE.search(msg)
    if conv_m:
        return {
            "type": "converted", "ts": ts,
            "recording": conv_m.group(1),
            "frames": int(conv_m.group(2)),
            "duration": float(conv_m.group(3)),
        }

    fail_m = _FAILED_RE.search(msg)
    if fail_m:
        return {
            "type": "failed", "ts": ts,
            "error_code": fail_m.group(1),
            "recording": fail_m.group(2),
            "reason": fail_m.group(3),
        }

    converting_m = _CONVERTING_RE.search(msg)
    if converting_m:
        return {
            "type": "converting", "ts": ts,
            "task": converting_m.group(1),
            "count": int(converting_m.group(2)),
        }

    scan_m = _SCAN_RE.search(msg)
    if scan_m:
        return {
            "type": "scan", "ts": ts,
            "tasks": int(scan_m.group(1)),
            "pending": int(scan_m.group(2)),
        }

    if level == "WARNING" and "anomal" in msg.lower():
        return {"type": "warning", "ts": ts, "message": msg}

    # Generic info/error that passed noise filter
    if level in ("INFO", "ERROR"):
        return {"type": level.lower(), "ts": ts, "message": msg}

    return None

_last_build_result: dict | None = None

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/converter", tags=["converter"])


@router.get("/status")
async def get_status():
    """Get converter container status and progress summary."""
    status = await converter_service.get_status()
    return {
        "container_state": status.container_state,
        "docker_available": status.docker_available,
        "tasks": [
            {
                "cell_task": t.cell_task,
                "total": t.total,
                "done": t.done,
                "pending": t.pending,
                "failed": t.failed,
                "retry": t.retry,
            }
            for t in status.tasks
        ],
        "summary": status.summary,
    }


@router.get("/progress")
async def get_progress():
    """Get conversion progress from state file + NAS scan."""
    tasks, summary = converter_service.build_progress()
    return {
        "tasks": [
            {
                "cell_task": t.cell_task,
                "total": t.total,
                "done": t.done,
                "pending": t.pending,
                "failed": t.failed,
                "retry": t.retry,
            }
            for t in tasks
        ],
        "summary": summary,
    }


@router.post("/build", status_code=202)
async def build():
    """Trigger Docker image build (async). Returns 202 immediately."""
    docker_ok = await converter_service.check_docker()
    if not docker_ok:
        raise HTTPException(503, "Docker daemon not available")

    if converter_service._build_lock.locked():
        raise HTTPException(409, "Build already in progress")

    async def _run_build():
        global _last_build_result
        lines: list[str] = []

        def collect(line: str):
            lines.append(line)

        exit_code = await converter_service.build_image(on_line=collect)
        _last_build_result = {
            "success": exit_code == 0,
            "exit_code": exit_code,
            "output": "\n".join(lines[-50:]),
        }

    asyncio.create_task(_run_build())
    return {"status": "build_started"}


@router.get("/build-result")
async def build_result():
    """Get the result of the last build."""
    if converter_service._build_lock.locked():
        return {"status": "building"}
    if _last_build_result is None:
        return {"status": "no_build"}
    return {"status": "complete", **_last_build_result}


@router.post("/start")
async def start():
    """Start auto_converter container."""
    docker_ok = await converter_service.check_docker()
    if not docker_ok:
        raise HTTPException(503, "Docker daemon not available")

    ok, msg = await converter_service.start_converter()
    if not ok:
        raise HTTPException(409, msg)
    return {"status": "started", "message": msg}


@router.post("/stop")
async def stop():
    """Stop converter container (idempotent)."""
    ok, msg = await converter_service.stop_converter()
    if not ok:
        raise HTTPException(500, msg)
    return {"status": "stopped", "message": msg}


@router.websocket("/logs")
async def logs_ws(ws: WebSocket):
    """Stream container logs via WebSocket."""
    await ws.accept()
    try:
        state = await converter_service.get_container_state()
        if state != "running":
            await ws.send_text("[converter not running]")
            await ws.close()
            return

        async for line in converter_service.stream_logs(tail=200):
            event = _parse_log_line(line)
            if event:
                await ws.send_text(json.dumps(event))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Log WebSocket error: %s", e)
    finally:
        try:
            await ws.close()
        except Exception:
            pass
