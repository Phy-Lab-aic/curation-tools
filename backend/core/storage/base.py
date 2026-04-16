"""Abstract storage backend interface.

Concrete implementations (LocalStorage, HFHubStorage, S3Storage, etc.)
provide the same async API over different storage systems.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class FileStat:
    path: str
    size: int
    is_dir: bool
    modified: float


class StorageBackend(ABC):
    """Abstract interface for filesystem-like storage backends."""

    @abstractmethod
    async def list(self, prefix: str) -> list[FileStat]: ...

    @abstractmethod
    async def read_bytes(self, path: str) -> bytes: ...

    @abstractmethod
    async def write_bytes(self, path: str, data: bytes) -> None: ...

    @abstractmethod
    async def exists(self, path: str) -> bool: ...

    @abstractmethod
    async def stat(self, path: str) -> FileStat: ...

    @abstractmethod
    async def delete(self, path: str) -> None: ...
