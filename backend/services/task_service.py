"""Backwards-compatibility shim — import from backend.datasets.services.task_service instead."""
from backend.datasets.services.task_service import *  # noqa: F401, F403
from backend.datasets.services.task_service import (  # noqa: F401
    get_tasks, get_task, update_task,
)
