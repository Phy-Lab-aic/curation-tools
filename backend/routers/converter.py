"""Converter control API — build/start/stop + status/progress."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.services import converter_service

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
    """Get conversion progress (parsed from latest scan table)."""
    tasks, summary = await converter_service.parse_progress()
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
            await ws.send_text(line)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("Log WebSocket error: %s", e)
    finally:
        try:
            await ws.close()
        except Exception:
            pass
