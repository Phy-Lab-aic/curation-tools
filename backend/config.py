"""Backwards-compatibility shim — import from backend.core.config instead."""
from backend.core.config import Settings, settings  # noqa: F401

__all__ = ["Settings", "settings"]
