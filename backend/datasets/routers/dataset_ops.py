"""FastAPI router for dataset split/merge operations."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, field_validator

from backend.config import settings
from backend.datasets.services.cycle_stamp_service import describe_stamp_state
from backend.datasets.services.dataset_ops_service import dataset_ops_service


def _validate_path(path_str: str) -> Path:
    """Resolve a dataset path and ensure it stays under an allowed root."""
    resolved = Path(path_str).resolve()
    allowed_roots = [Path(root).resolve() for root in settings.allowed_dataset_roots]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise HTTPException(status_code=400, detail=f"Path outside allowed roots: {path_str}")
    return resolved


def _validate_optional_path(path_str: str | None) -> str | None:
    """Resolve an optional dataset path when present."""
    if path_str is None:
        return None
    return str(_validate_path(path_str))

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/datasets", tags=["dataset-ops"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class SplitRequest(BaseModel):
    source_path: str
    episode_ids: list[int]
    target_name: str
    output_dir: str | None = None  # If omitted, sibling of source_path

    @field_validator("episode_ids")
    @classmethod
    def episode_ids_nonempty(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("episode_ids must not be empty")
        return v


class SplitIntoRequest(BaseModel):
    source_path: str
    episode_ids: list[int]
    target_name: str
    target_path: str | None = None  # If set, merge into this existing dataset
    output_dir: str | None = None  # Used when target_path is None

    @field_validator("episode_ids")
    @classmethod
    def episode_ids_nonempty(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("episode_ids must not be empty")
        return v


class DeleteRequest(BaseModel):
    source_path: str
    episode_ids: list[int]
    output_dir: str | None = None  # If omitted, overwrites source in-place

    @field_validator("episode_ids")
    @classmethod
    def episode_ids_nonempty(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("episode_ids must not be empty")
        return v


class MergeRequest(BaseModel):
    source_paths: list[str]
    target_name: str
    output_dir: str | None = None  # If omitted, sibling of first source_path


class StampCyclesRequest(BaseModel):
    source_path: str
    overwrite: bool = False


class JobResponse(BaseModel):
    job_id: str
    operation: str
    status: str


class JobStatusResponse(BaseModel):
    job_id: str
    operation: str
    status: str
    created_at: str
    completed_at: str | None = None
    error: str | None = None
    result_path: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/split", response_model=JobResponse, status_code=202)
async def split_dataset(req: SplitRequest):
    """Split episodes from a source dataset into a new derived dataset."""
    source = _validate_path(req.source_path)
    output_dir = _validate_optional_path(req.output_dir)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Source path not found: {req.source_path}")

    job_id = await dataset_ops_service.split_dataset(
        source_path=req.source_path,
        episode_ids=req.episode_ids,
        target_name=req.target_name,
        output_dir=output_dir,
    )
    return JobResponse(job_id=job_id, operation="split", status="queued")


@router.post("/split-into", response_model=JobResponse, status_code=202)
async def split_into_dataset(req: SplitIntoRequest):
    """Split episodes into a new dataset, or merge them into an existing one."""
    source = _validate_path(req.source_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Source path not found: {req.source_path}")

    if req.target_path is None:
        # New dataset mode — create new derived dataset
        output_dir = _validate_optional_path(req.output_dir)
        job_id = await dataset_ops_service.split_dataset(
            source_path=req.source_path,
            episode_ids=req.episode_ids,
            target_name=req.target_name,
            output_dir=output_dir,
        )
        return JobResponse(job_id=job_id, operation="split", status="queued")
    else:
        # Existing dataset mode — split then merge into target
        target = _validate_path(req.target_path)
        if not target.exists():
            raise HTTPException(status_code=404, detail=f"Target path not found: {req.target_path}")
        job_id = await dataset_ops_service.split_and_merge(
            source_path=req.source_path,
            episode_ids=req.episode_ids,
            target_path=req.target_path,
            target_name=req.target_name,
        )
        return JobResponse(job_id=job_id, operation="split_and_merge", status="queued")


@router.post("/merge", response_model=JobResponse, status_code=202)
async def merge_datasets(req: MergeRequest):
    """Merge multiple source datasets into a new derived dataset."""
    output_dir = _validate_optional_path(req.output_dir)
    for sp in req.source_paths:
        source = _validate_path(sp)
        if not source.exists():
            raise HTTPException(status_code=404, detail=f"Source path not found: {sp}")

    job_id = await dataset_ops_service.merge_datasets(
        source_paths=req.source_paths,
        target_name=req.target_name,
        output_dir=output_dir,
    )
    return JobResponse(job_id=job_id, operation="merge", status="queued")


@router.post("/delete", response_model=JobResponse, status_code=202)
async def delete_episodes(req: DeleteRequest):
    """Delete specified episodes from a dataset, producing a new dataset."""
    source = _validate_path(req.source_path)
    output_dir = _validate_optional_path(req.output_dir)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Source path not found: {req.source_path}")

    job_id = await dataset_ops_service.delete_episodes(
        source_path=req.source_path,
        episode_ids=req.episode_ids,
        output_dir=output_dir,
    )
    return JobResponse(job_id=job_id, operation="delete", status="queued")


@router.post("/stamp-cycles", response_model=JobResponse, status_code=202)
async def stamp_cycles(req: StampCyclesRequest):
    """Queue cycle stamping for a dataset under an allowed root."""
    source = _validate_path(req.source_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Source path not found: {req.source_path}")

    job_id = await dataset_ops_service.stamp_cycles(
        source_path=str(source),
        overwrite=req.overwrite,
    )
    return JobResponse(job_id=job_id, operation="stamp_cycles", status="queued")


@router.get("/stamp-cycles/status")
async def get_stamp_cycles_status(path: str = Query(..., description="Dataset path to inspect")):
    """Describe whether cycle stamps exist for a dataset."""
    source = _validate_path(path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Source path not found: {path}")
    return describe_stamp_state(source)


@router.get("/ops/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Return status of a dataset operation job."""
    job = dataset_ops_service.get_job_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return JobStatusResponse(
        job_id=job["id"],
        operation=job["operation"],
        status=job["status"],
        created_at=job["created_at"],
        completed_at=job.get("completed_at"),
        error=job.get("error"),
        result_path=job.get("result_path"),
    )
