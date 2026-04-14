from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from backend.config import settings
from backend.models.schemas import DatasetExportRequest, DatasetInfo, DatasetLoadRequest
from backend.services.dataset_service import dataset_service
from backend.services.export_service import export_dataset

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _default_scan_root() -> Path:
    configured = Path(settings.dataset_path)
    if configured.exists() and configured.is_dir():
        return configured

    for root in settings.allowed_dataset_roots:
        candidate = Path(root)
        if candidate.exists() and candidate.is_dir():
            return candidate

    return configured


@router.get("/list")
async def list_datasets(root: str | None = Query(None, description="Root directory to scan for LeRobot datasets")):
    """Scan the configured dataset root for valid LeRobot datasets (dirs with meta/info.json)."""
    root_path = Path(root) if root else _default_scan_root()
    if not root_path.exists() or not root_path.is_dir():
        return []

    datasets = []
    for child in sorted(root_path.iterdir()):
        if child.is_dir() and (child / "meta" / "info.json").exists():
            datasets.append({"name": child.name, "path": str(child.resolve())})
    return datasets


@router.post("/load", response_model=DatasetInfo)
async def load_dataset(req: DatasetLoadRequest):
    try:
        dataset_service.load_dataset(req.path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    info = dataset_service.get_info()
    return DatasetInfo(
        path=str(dataset_service.dataset_path),
        name=info.get("robot_type", dataset_service.dataset_path.name),
        fps=info.get("fps", 0),
        total_episodes=info.get("total_episodes", len(dataset_service.get_episodes())),
        total_tasks=info.get("total_tasks", len(dataset_service.get_tasks())),
        robot_type=info.get("robot_type"),
        features=info.get("features", {}),
    )


@router.get("/info", response_model=DatasetInfo)
async def get_info():
    try:
        info = dataset_service.get_info()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return DatasetInfo(
        path=str(dataset_service.dataset_path),
        name=info.get("robot_type", dataset_service.dataset_path.name),
        fps=info.get("fps", 0),
        total_episodes=info.get("total_episodes", len(dataset_service.get_episodes())),
        total_tasks=info.get("total_tasks", len(dataset_service.get_tasks())),
        robot_type=info.get("robot_type"),
        features=info.get("features", {}),
    )


@router.post("/export")
async def export_dataset_endpoint(req: DatasetExportRequest):
    """Export the loaded dataset, excluding episodes with specified grades."""
    try:
        result = export_dataset(req.output_path, req.exclude_grades)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return result
