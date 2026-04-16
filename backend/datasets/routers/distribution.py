"""Router for dataset distribution analysis endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.core.config import settings
from backend.datasets.schemas import (
    DistributionRequest,
    DistributionResponse,
    FieldInfo,
)
from backend.datasets.services.distribution_service import (
    compute_distribution,
    get_available_fields,
)

router = APIRouter(prefix="/api/datasets", tags=["distribution"])


@router.get("/fields", response_model=list[FieldInfo])
async def list_fields(dataset_path: str):
    """Return all available fields in episode parquet files."""
    resolved = Path(dataset_path).resolve()
    allowed_roots = [Path(r).resolve() for r in settings.allowed_dataset_roots]
    if not any(resolved == root or str(resolved).startswith(str(root) + "/") for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed roots")

    try:
        return get_available_fields(dataset_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/distribution", response_model=DistributionResponse)
async def get_distribution(req: DistributionRequest):
    """Compute value distribution for a selected field."""
    resolved = Path(req.dataset_path).resolve()
    allowed_roots = [Path(r).resolve() for r in settings.allowed_dataset_roots]
    if not any(resolved == root or str(resolved).startswith(str(root) + "/") for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed roots")

    try:
        return compute_distribution(req.dataset_path, req.field, req.chart_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
