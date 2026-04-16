"""Backwards-compatibility shim — import from backend.datasets.services.dataset_ops_service instead."""
from backend.datasets.services.dataset_ops_service import *  # noqa: F401, F403
from backend.datasets.services.dataset_ops_service import (  # noqa: F401
    DatasetOpsService, dataset_ops_service,
)
