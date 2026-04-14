"""Router for cell and dataset listing endpoints."""

from fastapi import APIRouter, HTTPException
import urllib.parse
from pathlib import Path

from backend.config import settings
from backend.models.schemas import CellInfo, DatasetSummary
from backend.services.cell_service import get_datasets_in_cell, scan_cells

router = APIRouter(prefix="/api/cells", tags=["cells"])


@router.get("", response_model=list[CellInfo])
async def list_cells():
    """Scan allowed_dataset_roots for cell* directories."""
    return scan_cells(settings.allowed_dataset_roots, pattern=settings.cell_name_pattern)


@router.get("/{cell_path:path}/datasets", response_model=list[DatasetSummary])
async def list_datasets_in_cell(cell_path: str):
    """List datasets inside a cell directory.

    cell_path is the full absolute path to the cell directory,
    URL-encoded by the client.
    """
    decoded = urllib.parse.unquote(cell_path)
    datasets = get_datasets_in_cell(decoded)
    if not datasets and not Path(decoded).exists():
        raise HTTPException(status_code=404, detail=f"Cell path not found: {decoded}")
    return datasets
