"""FastAPI router for the rosbag→LeRobot conversion pipeline."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.services.conversion_service import ConversionService, conversion_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversion", tags=["conversion"])


# ---------------------------------------------------------------------------
# Dependency injection (allows test override)
# ---------------------------------------------------------------------------

def get_conversion_service() -> ConversionService:
    return conversion_service


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ProfileCreateRequest(BaseModel):
    name: str
    config: dict[str, Any]


class WatchStartRequest(BaseModel):
    profile_name: str


class RunOnceRequest(BaseModel):
    profile_name: str


class JobResponse(BaseModel):
    id: str
    folder: str
    status: str
    message: str
    created_at: str
    finished_at: str | None = None


# ---------------------------------------------------------------------------
# Profile endpoints
# ---------------------------------------------------------------------------

@router.get("/configs")
async def list_configs(svc: ConversionService = Depends(get_conversion_service)):
    return svc.list_profiles()


@router.post("/configs", status_code=201)
async def create_config(
    req: ProfileCreateRequest,
    svc: ConversionService = Depends(get_conversion_service),
):
    svc.save_profile(req.name, req.config)
    return {"name": req.name}


@router.put("/configs/{name}")
async def update_config(
    name: str,
    req: ProfileCreateRequest,
    svc: ConversionService = Depends(get_conversion_service),
):
    svc.save_profile(name, req.config)
    return {"name": name}


@router.get("/configs/{name}")
async def get_config(
    name: str,
    svc: ConversionService = Depends(get_conversion_service),
):
    try:
        return svc.load_profile(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profile not found: {name}")


@router.delete("/configs/{name}", status_code=204)
async def delete_config(
    name: str,
    svc: ConversionService = Depends(get_conversion_service),
):
    try:
        svc.delete_profile(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profile not found: {name}")


# ---------------------------------------------------------------------------
# Watch endpoints
# ---------------------------------------------------------------------------

@router.get("/watch/status")
async def watch_status(svc: ConversionService = Depends(get_conversion_service)):
    return svc.get_watch_status()


@router.post("/watch/start")
async def start_watch(
    req: WatchStartRequest,
    svc: ConversionService = Depends(get_conversion_service),
):
    try:
        svc.start_watching(req.profile_name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"watching": True}


@router.post("/watch/stop")
async def stop_watch(svc: ConversionService = Depends(get_conversion_service)):
    svc.stop_watching()
    return {"watching": False}


# ---------------------------------------------------------------------------
# Manual run
# ---------------------------------------------------------------------------

@router.post("/run", status_code=202)
async def run_once(
    req: RunOnceRequest,
    svc: ConversionService = Depends(get_conversion_service),
):
    """Scan input_path for all unconverted MCAP folders and queue them."""
    try:
        profile = svc.load_profile(req.profile_name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profile not found: {req.profile_name}")

    input_path = Path(profile.get("input_path", ""))
    if not input_path.exists():
        raise HTTPException(status_code=400, detail=f"Input path does not exist: {input_path}")

    queued = []
    for d in sorted(input_path.iterdir()):
        if d.is_dir() and d.name != "processed" and any(d.glob("*.mcap")):
            job_id = svc.submit_folder(d.name, profile)
            if job_id:
                queued.append({"folder": d.name, "job_id": job_id})

    return {"queued": queued}


# ---------------------------------------------------------------------------
# Job list + SSE stream
# ---------------------------------------------------------------------------

@router.get("/jobs", response_model=list[JobResponse])
async def get_jobs(svc: ConversionService = Depends(get_conversion_service)):
    return svc.get_jobs()


@router.get("/jobs/stream")
async def stream_jobs(svc: ConversionService = Depends(get_conversion_service)):
    """SSE endpoint — sends job list every second."""
    async def event_generator():
        try:
            while True:
                jobs = svc.get_jobs()
                data = json.dumps(jobs)
                yield f"data: {data}\n\n"
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
