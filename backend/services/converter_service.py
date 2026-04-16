"""Backwards-compatibility shim — import from backend.converter.service instead."""
from backend.converter.service import *  # noqa: F401, F403
from backend.converter.service import (  # noqa: F401  — private names for tests
    _ROW_RE, _TOTAL_RE, _build_lock,
    TaskProgress, ConverterStatus, parse_progress, get_status,
    check_docker, build_image, start_converter, stop_converter,
    get_container_state, stream_logs,
)
