from fastapi import APIRouter, HTTPException

from backend.models.schemas import Episode, EpisodeUpdate
from backend.services.episode_service import episode_service, EpisodeNotFoundError

router = APIRouter(prefix="/api/episodes", tags=["episodes"])


@router.get("", response_model=list[Episode])
async def list_episodes():
    try:
        return await episode_service.get_episodes()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{episode_index}", response_model=Episode)
async def get_episode(episode_index: int):
    try:
        return await episode_service.get_episode(episode_index)
    except EpisodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{episode_index}", response_model=Episode)
async def update_episode(episode_index: int, update: EpisodeUpdate):
    try:
        return await episode_service.update_episode(
            episode_index=episode_index,
            grade=update.grade,
            tags=update.tags if update.tags is not None else [],
        )
    except EpisodeNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
