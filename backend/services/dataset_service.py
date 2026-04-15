"""Backwards-compatibility shim — import from backend.datasets.services.dataset_service instead."""
from backend.datasets.services.dataset_service import *  # noqa: F401, F403
from backend.datasets.services.dataset_service import (  # noqa: F401
    DatasetService, dataset_service,
)
