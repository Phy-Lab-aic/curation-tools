"""Router for dataset field management endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException

from backend.config import settings
from backend.models.schemas import EpisodeColumnAdd, InfoFieldUpdate
from backend.services.fields_service import (
    add_episode_column,
    delete_info_field,
    get_episode_columns,
    get_info_fields,
    update_info_field,
)

router = APIRouter(prefix="/api/datasets", tags=["fields"])


def _validate_path(dataset_path: str) -> None:
    resolved = Path(dataset_path).resolve()
    allowed_roots = [Path(r).resolve() for r in settings.allowed_dataset_roots]
    if not any(resolved == root or str(resolved).startswith(str(root) + "/") for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed roots")


@router.get("/info-fields")
async def list_info_fields(dataset_path: str):
    """Return all fields from info.json."""
    _validate_path(dataset_path)
    try:
        return get_info_fields(dataset_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset not found")


@router.patch("/info-fields")
async def update_info(dataset_path: str, req: InfoFieldUpdate):
    """Add or update a custom field in info.json."""
    _validate_path(dataset_path)
    try:
        if req.value is None:
            delete_info_field(dataset_path, req.key)
        else:
            update_info_field(dataset_path, req.key, req.value)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/episode-columns")
async def list_episode_columns(dataset_path: str):
    """Return all columns from episode parquet files."""
    _validate_path(dataset_path)
    return get_episode_columns(dataset_path)


@router.post("/episode-columns")
async def add_column(req: EpisodeColumnAdd):
    """Add a new column to all episode parquet files."""
    _validate_path(req.dataset_path)
    try:
        add_episode_column(req.dataset_path, req.column_name, req.dtype, req.default_value)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
