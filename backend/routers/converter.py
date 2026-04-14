"""Converter control API — build/start/stop + status/progress."""

import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.services import converter_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/converter", tags=["converter"])


@router.get("/status")
async def get_status():
    """Get converter container status and progress summary."""
    status = converter_service.get_status()
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
    tasks, summary = converter_service.parse_progress()
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


@router.post("/build")
async def build():
    """Trigger Docker image build. Returns when build completes."""
    docker_ok = converter_service.check_docker()
    if not docker_ok:
        raise HTTPException(503, "Docker daemon not available")

    lines: list[str] = []

    def collect(line: str):
        lines.append(line)

    exit_code = await converter_service.build_image(on_line=collect)
    return {
        "success": exit_code == 0,
        "exit_code": exit_code,
        "output": "\n".join(lines[-50:]),
    }


@router.post("/start")
async def start():
    """Start auto_converter container."""
    docker_ok = converter_service.check_docker()
    if not docker_ok:
        raise HTTPException(503, "Docker daemon not available")

    state = converter_service.get_container_state()
    if state == "running":
        raise HTTPException(409, "Container already running")

    ok, msg = converter_service.start_converter()
    if not ok:
        raise HTTPException(500, msg)
    return {"status": "started", "message": msg}


@router.post("/stop")
async def stop():
    """Stop converter container (idempotent)."""
    ok, msg = converter_service.stop_converter()
    if not ok:
        raise HTTPException(500, msg)
    return {"status": "stopped", "message": msg}


@router.websocket("/logs")
async def logs_ws(ws: WebSocket):
    """Stream container logs via WebSocket."""
    await ws.accept()
    try:
        state = converter_service.get_container_state()
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
