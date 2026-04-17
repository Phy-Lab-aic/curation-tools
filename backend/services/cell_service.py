"""Backwards-compatible cell service exports for legacy and async callers."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from backend.datasets.services.cell_service import *  # noqa: F401, F403
from backend.datasets.services.cell_service import (  # noqa: F401
    get_datasets_in_cell as _async_get_datasets_in_cell,
    scan_cells,
)
from backend.datasets.schemas import DatasetSummary


def get_datasets_in_cell(
    cell_path: str,
) -> list[DatasetSummary] | Coroutine[Any, Any, list[DatasetSummary]]:
    """Preserve sync behavior for legacy imports while keeping async support."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_async_get_datasets_in_cell(cell_path))
    return _async_get_datasets_in_cell(cell_path)
