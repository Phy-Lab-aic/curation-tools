"""Backwards-compatibility shim — import from backend.datasets.services.episode_service instead."""
from backend.datasets.services.episode_service import *  # noqa: F401, F403
from backend.datasets.services.episode_service import (  # noqa: F401
    EpisodeNotFoundError, EpisodeService, episode_service,
    _load_sidecar, _load_sidecar_json, _sidecar_file,
    _ensure_dataset_registered, _ensure_migrated,
    _load_annotations_from_db, _save_annotation_to_db,
    _get_dataset_id, _refresh_dataset_stats,
)
