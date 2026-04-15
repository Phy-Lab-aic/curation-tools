"""Local/NAS filesystem storage backend."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .base import FileStat, StorageBackend


class LocalStorage(StorageBackend):
    """Storage backend for local/NAS filesystem access."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, path: str) -> Path:
        resolved = (self._root / path).resolve()
        if not resolved.is_relative_to(self._root):
            raise ValueError(f"Path escapes storage root: {path}")
        return resolved

    async def list(self, prefix: str = "") -> list[FileStat]:
        target = self._resolve(prefix)
        if not target.is_dir():
            return []

        def _scan() -> list[FileStat]:
            return [
                FileStat(
                    path=str(child.relative_to(self._root)),
                    size=child.stat().st_size if child.is_file() else 0,
                    is_dir=child.is_dir(),
                    modified=child.stat().st_mtime,
                )
                for child in sorted(target.iterdir())
            ]

        return await asyncio.to_thread(_scan)

    async def read_bytes(self, path: str) -> bytes:
        resolved = self._resolve(path)
        return await asyncio.to_thread(resolved.read_bytes)

    async def write_bytes(self, path: str, data: bytes) -> None:
        resolved = self._resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(resolved.write_bytes, data)

    async def exists(self, path: str) -> bool:
        resolved = self._resolve(path)
        return await asyncio.to_thread(resolved.exists)

    async def stat(self, path: str) -> FileStat:
        resolved = self._resolve(path)
        st = await asyncio.to_thread(resolved.stat)
        return FileStat(
            path=path,
            size=st.st_size,
            is_dir=resolved.is_dir(),
            modified=st.st_mtime,
        )

    async def delete(self, path: str) -> None:
        resolved = self._resolve(path)
        if resolved.is_dir():
            import shutil

            await asyncio.to_thread(shutil.rmtree, resolved)
        else:
            await asyncio.to_thread(resolved.unlink)
