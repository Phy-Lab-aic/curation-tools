"""Backwards-compatibility shim — import from backend.datasets.services.fields_service instead."""
from backend.datasets.services.fields_service import *  # noqa: F401, F403
from backend.datasets.services.fields_service import (  # noqa: F401
    add_episode_column, delete_info_field, get_episode_columns,
    get_info_fields, update_info_field,
)
