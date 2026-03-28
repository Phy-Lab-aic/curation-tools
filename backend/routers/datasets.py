from fastapi import APIRouter, HTTPException

from backend.models.schemas import DatasetInfo, DatasetLoadRequest
from backend.services.dataset_service import dataset_service

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


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
