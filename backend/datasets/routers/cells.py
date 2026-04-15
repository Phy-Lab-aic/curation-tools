"""Router for cell and dataset listing endpoints."""

from fastapi import APIRouter, HTTPException
import urllib.parse
from pathlib import Path

from backend.core.config import settings
from backend.datasets.schemas import CellInfo, DatasetSummary
from backend.datasets.services.cell_service import get_datasets_in_cell, scan_cells

router = APIRouter(prefix="/api/cells", tags=["cells"])


@router.get("", response_model=list[CellInfo])
async def list_cells():
    """Scan allowed_dataset_roots for cell* directories."""
    return scan_cells(settings.allowed_dataset_roots, pattern=settings.cell_name_pattern)


@router.get("/{cell_path:path}/datasets", response_model=list[DatasetSummary])
async def list_datasets_in_cell(cell_path: str):
    """List datasets inside a cell directory.

    cell_path: Full absolute path to the cell directory, URL-encoded.
               Must be within an allowed_dataset_root.
    """
    decoded = urllib.parse.unquote(cell_path)
    resolved = Path(decoded).resolve()

    # Validate path is within an allowed root
    allowed_roots = [Path(r).resolve() for r in settings.allowed_dataset_roots]
    if not any(resolved == root or str(resolved).startswith(str(root) + "/") for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Access denied: path outside allowed roots")

    datasets = get_datasets_in_cell(decoded)
    if not Path(decoded).exists():
        raise HTTPException(status_code=404, detail=f"Cell path not found: {decoded}")
    return datasets
