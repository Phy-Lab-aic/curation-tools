from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from backend.core.config import settings

_SYNC_FN: Callable[[Path, list[int], Path], Any] | None = None
_SYNC_SOURCE_ROOT: Path | None = None


def load_sync_selected_episodes() -> Callable[[Path, list[int], Path], Any]:
    global _SYNC_FN, _SYNC_SOURCE_ROOT

    repo_root = _resolve_repo_root(Path(settings.rosbag_to_lerobot_repo_path))

    if _SYNC_FN is not None and _SYNC_SOURCE_ROOT == repo_root:
        return _SYNC_FN

    if _SYNC_SOURCE_ROOT is not None and _SYNC_SOURCE_ROOT != repo_root:
        _drop_cached_conversion_modules()

    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)

    importlib.invalidate_caches()
    module = importlib.import_module("conversion.dataset_sync")
    sync_fn = getattr(module, "sync_selected_episodes", None)
    if sync_fn is None:
        raise RuntimeError("conversion.dataset_sync.sync_selected_episodes is missing")

    _SYNC_FN = sync_fn
    _SYNC_SOURCE_ROOT = repo_root
    return sync_fn


def _drop_cached_conversion_modules() -> None:
    for module_name in ("conversion.dataset_sync", "conversion"):
        module = sys.modules.get(module_name)
        if not isinstance(module, ModuleType):
            continue
        module_file = getattr(module, "__file__", None)
        if module_file:
            sys.modules.pop(module_name, None)


def _resolve_repo_root(configured_root: Path) -> Path:
    repo_root = configured_root.resolve()
    if not repo_root.is_dir():
        raise RuntimeError(f"rosbag-to-lerobot checkout not found: {repo_root}")

    if (repo_root / "conversion" / "dataset_sync.py").is_file():
        return repo_root

    worktree_matches = sorted((repo_root / ".worktrees").glob("*/conversion/dataset_sync.py"))
    if len(worktree_matches) == 1:
        return worktree_matches[0].parent.parent

    raise RuntimeError(f"conversion.dataset_sync not found under: {repo_root}")
