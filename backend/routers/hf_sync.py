import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.hf_sync_service import hf_sync_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hf-sync", tags=["hf-sync"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class SyncStatusResponse(BaseModel):
    org: str
    mounted_repos: list[str]
    mount_details: dict
    last_scan: Optional[str]
    errors: list[str]
    initialized: bool


class ScanResponse(BaseModel):
    scanned: int
    new_mounts: list[str]
    already_mounted: list[str]
    failed: list[str]


class MountResponse(BaseModel):
    success: bool
    repo_id: str
    mount_point: Optional[str] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/status", response_model=SyncStatusResponse)
async def get_status():
    """Return current HF sync state."""
    status = hf_sync_service.get_status()
    return SyncStatusResponse(
        org=status["org"],
        mounted_repos=status["mounted_repos"],
        mount_details=status["mount_details"],
        last_scan=status["last_scan"],
        errors=status["errors"],
        initialized=status["initialized"],
    )


@router.post("/scan", response_model=ScanResponse)
async def trigger_scan():
    """Trigger an immediate scan of HF org repos and mount any new ones."""
    try:
        result = await hf_sync_service.scan()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ScanResponse(
        scanned=result["scanned"],
        new_mounts=result["new_mounts"],
        already_mounted=result["already_mounted"],
        failed=result["failed"],
    )


@router.post("/repos/{repo_id:path}/mount", response_model=MountResponse)
async def mount_repo(repo_id: str):
    """Manually mount a specific HF dataset repo."""
    if not hf_sync_service._initialized:
        raise HTTPException(status_code=400, detail="HF sync service not initialized")
    ok = await hf_sync_service.mount_repo(repo_id)
    if ok:
        mount_point = hf_sync_service._mounted.get(repo_id, {}).get("mount_point")
        return MountResponse(success=True, repo_id=repo_id, mount_point=mount_point)
    else:
        last_error = hf_sync_service._errors[-1] if hf_sync_service._errors else "Unknown error"
        return MountResponse(success=False, repo_id=repo_id, error=last_error)


@router.post("/repos/{repo_id:path}/unmount", response_model=MountResponse)
async def unmount_repo(repo_id: str):
    """Manually unmount a specific HF dataset repo."""
    if not hf_sync_service._initialized:
        raise HTTPException(status_code=400, detail="HF sync service not initialized")
    ok = await hf_sync_service.unmount_repo(repo_id)
    if ok:
        return MountResponse(success=True, repo_id=repo_id)
    else:
        last_error = hf_sync_service._errors[-1] if hf_sync_service._errors else "Unknown error"
        return MountResponse(success=False, repo_id=repo_id, error=last_error)
