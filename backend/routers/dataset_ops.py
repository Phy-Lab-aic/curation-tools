"""FastAPI router for dataset split/merge operations."""

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from backend.services.dataset_ops_service import dataset_ops_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/datasets", tags=["dataset-ops"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class SplitRequest(BaseModel):
    source_path: str
    episode_ids: list[int]
    target_name: str

    @field_validator("episode_ids")
    @classmethod
    def episode_ids_nonempty(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("episode_ids must not be empty")
        return v


class MergeRequest(BaseModel):
    source_paths: list[str]
    target_name: str


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


class DerivedDatasetInfo(BaseModel):
    name: str
    path: str
    has_provenance: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derived_names() -> set[str]:
    return {d["name"] for d in dataset_ops_service.list_derived_datasets()}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/split", response_model=JobResponse, status_code=202)
async def split_dataset(req: SplitRequest):
    """Split episodes from a source dataset into a new derived dataset."""
    source = Path(req.source_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Source path not found: {req.source_path}")

    if req.target_name in _derived_names():
        raise HTTPException(
            status_code=409,
            detail=f"Derived dataset '{req.target_name}' already exists",
        )

    job_id = await dataset_ops_service.split_dataset(
        source_path=req.source_path,
        episode_ids=req.episode_ids,
        target_name=req.target_name,
    )
    return JobResponse(job_id=job_id, operation="split", status="queued")


@router.post("/merge", response_model=JobResponse, status_code=202)
async def merge_datasets(req: MergeRequest):
    """Merge multiple source datasets into a new derived dataset."""
    for sp in req.source_paths:
        if not Path(sp).exists():
            raise HTTPException(status_code=404, detail=f"Source path not found: {sp}")

    if req.target_name in _derived_names():
        raise HTTPException(
            status_code=409,
            detail=f"Derived dataset '{req.target_name}' already exists",
        )

    job_id = await dataset_ops_service.merge_datasets(
        source_paths=req.source_paths,
        target_name=req.target_name,
    )
    return JobResponse(job_id=job_id, operation="merge", status="queued")


@router.get("/derived", response_model=list[DerivedDatasetInfo])
async def list_derived_datasets():
    """List all derived datasets."""
    items = dataset_ops_service.list_derived_datasets()
    return [
        DerivedDatasetInfo(
            name=item["name"],
            path=item["path"],
            has_provenance="provenance" in item and item["provenance"] is not None,
        )
        for item in items
    ]


@router.get("/derived/{name}/provenance")
async def get_provenance(name: str):
    """Return provenance metadata for a derived dataset."""
    provenance = dataset_ops_service.get_provenance(name)
    if provenance is None:
        raise HTTPException(
            status_code=404,
            detail=f"No provenance found for dataset '{name}'",
        )
    return provenance


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
