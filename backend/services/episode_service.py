"""Service for reading and writing episode metadata in LeRobot v3.0 parquet files.

Episode metadata (grade, tags) is stored alongside the episode records in chunked
parquet files located at ``meta/episodes/chunk-{N}/file-{M}.parquet``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from backend.models.schemas import Episode
from backend.services.dataset_service import dataset_service

logger = logging.getLogger(__name__)


class EpisodeNotFoundError(Exception):
    """Raised when an episode_index cannot be located in any parquet file."""


class EpisodeService:
    """Reads and writes episode metadata for a loaded LeRobot v3.0 dataset.

    All mutation operations acquire a per-file asyncio lock (provided by
    ``dataset_service``) before touching the parquet file, ensuring that
    concurrent requests for the same file are serialized.

    The service maintains a small in-memory cache of ``Episode`` dicts
    (keyed by ``episode_index``) that is populated lazily on the first call
    to :meth:`get_episodes` and kept up-to-date by :meth:`update_episode`.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_episodes(self) -> list[dict[str, Any]]:
        """Return all episodes, merging grade/tags and denormalizing task instructions.

        Returns
        -------
        list[dict]
            Each dict corresponds to one :class:`~backend.models.schemas.Episode`.
        """
        if dataset_service.episodes_cache is not None:
            return list(dataset_service.episodes_cache.values())

        episodes: dict[int, dict[str, Any]] = {}
        tasks_map = await dataset_service.get_tasks_map()

        for file_path in dataset_service.iter_episode_parquet_files():
            table = await asyncio.to_thread(pq.read_table, file_path)
            for row in _iter_rows(table):
                ep = _row_to_episode(row, tasks_map)
                episodes[ep["episode_index"]] = ep

        dataset_service.episodes_cache = episodes
        return list(episodes.values())

    async def get_episode(self, episode_index: int) -> dict[str, Any]:
        """Return a single episode by its index.

        Parameters
        ----------
        episode_index:
            Zero-based index of the episode to retrieve.

        Raises
        ------
        EpisodeNotFoundError
            If no parquet file contains a row with the given ``episode_index``.
        """
        # Fast path: use cache if populated
        if dataset_service.episodes_cache is not None:
            try:
                return dataset_service.episodes_cache[episode_index]
            except KeyError:
                raise EpisodeNotFoundError(
                    f"Episode {episode_index} not found in cache."
                )

        # Slow path: scan files
        tasks_map = await dataset_service.get_tasks_map()
        file_path = dataset_service.get_file_for_episode(episode_index)
        if file_path is None:
            raise EpisodeNotFoundError(
                f"Episode {episode_index} not found in any parquet file."
            )

        table = await asyncio.to_thread(pq.read_table, file_path)
        for row in _iter_rows(table):
            if row.get("episode_index") == episode_index:
                return _row_to_episode(row, tasks_map)

        raise EpisodeNotFoundError(
            f"Episode {episode_index} not found in {file_path}."
        )

    async def update_episode(
        self,
        episode_index: int,
        grade: str | None,
        tags: list[str],
    ) -> dict[str, Any]:
        """Persist grade and tags for *episode_index* in the parquet file.

        The update is atomic: the new table is written to a temporary file in
        the same directory and then renamed over the original.

        Parameters
        ----------
        episode_index:
            Zero-based index of the episode to update.
        grade:
            Letter grade (``"A"``–``"F"``), or ``None`` to clear.
        tags:
            List of tag strings (may be empty).

        Returns
        -------
        dict
            The updated episode record.

        Raises
        ------
        EpisodeNotFoundError
            If ``episode_index`` cannot be located in any file.
        """
        file_path = dataset_service.get_file_for_episode(episode_index)
        if file_path is None:
            raise EpisodeNotFoundError(
                f"Episode {episode_index} not found in episode-to-file index."
            )

        lock = dataset_service.get_file_lock(file_path)
        async with lock:
            table = await asyncio.to_thread(pq.read_table, file_path)
            table = _ensure_metadata_columns(table)
            table = _update_row(table, episode_index, grade, tags)
            await asyncio.to_thread(_atomic_write, table, file_path)

        tasks_map = await dataset_service.get_tasks_map()
        # Find the updated row and return it
        for row in _iter_rows(table):
            if row.get("episode_index") == episode_index:
                ep = _row_to_episode(row, tasks_map)
                # Sync cache
                if dataset_service.episodes_cache is not None:
                    dataset_service.episodes_cache[episode_index] = ep
                return ep

        # Should never reach here, but be defensive
        raise EpisodeNotFoundError(
            f"Episode {episode_index} missing after write to {file_path}."
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iter_rows(table: pa.Table):
    """Yield each row of *table* as a plain Python dict."""
    col_names = table.schema.names
    for batch in table.to_batches():
        col_arrays = {name: batch.column(name).to_pylist() for name in col_names}
        n = batch.num_rows
        for i in range(n):
            yield {name: col_arrays[name][i] for name in col_names}


def _row_to_episode(
    row: dict[str, Any],
    tasks_map: dict[int, str],
) -> dict[str, Any]:
    """Convert a raw parquet row dict into an Episode-compatible dict."""
    task_index: int = row.get("task_index", 0)
    task_instruction: str = tasks_map.get(task_index, "")

    # Normalise tags: parquet stores None when the list is absent
    raw_tags = row.get("tags")
    tags: list[str] = raw_tags if isinstance(raw_tags, list) else []

    return Episode(
        episode_index=row["episode_index"],
        length=int(row.get("dataset_to_index", 0)) - int(row.get("dataset_from_index", 0)),
        task_index=task_index,
        task_instruction=task_instruction,
        chunk_index=int(row.get("data/chunk_index", 0)),
        file_index=int(row.get("data/file_index", 0)),
        dataset_from_index=int(row.get("dataset_from_index", 0)),
        dataset_to_index=int(row.get("dataset_to_index", 0)),
        grade=row.get("grade"),
        tags=tags,
    ).model_dump()


def _ensure_metadata_columns(table: pa.Table) -> pa.Table:
    """Add *grade* and *tags* columns to *table* if they are absent.

    ``grade`` is ``pa.string()`` (nullable).
    ``tags`` is ``pa.list_(pa.string())`` (nullable, default empty list).
    """
    n = len(table)
    schema = table.schema

    if "grade" not in schema.names:
        grade_array = pa.array([None] * n, type=pa.string())
        table = table.append_column(
            pa.field("grade", pa.string(), nullable=True),
            grade_array,
        )

    if "tags" not in schema.names:
        tags_array = pa.array([[]] * n, type=pa.list_(pa.string()))
        table = table.append_column(
            pa.field("tags", pa.list_(pa.string()), nullable=True),
            tags_array,
        )

    return table


def _update_row(
    table: pa.Table,
    episode_index: int,
    grade: str | None,
    tags: list[str],
) -> pa.Table:
    """Return a new table with grade/tags set for the row matching *episode_index*.

    Raises
    ------
    EpisodeNotFoundError
        If no row has ``episode_index`` equal to *episode_index*.
    """
    ep_col: pa.Array = table.column("episode_index")
    indices = [i for i, v in enumerate(ep_col.to_pylist()) if v == episode_index]

    if not indices:
        raise EpisodeNotFoundError(
            f"Episode {episode_index} not found in table being updated."
        )

    row_idx = indices[0]

    # Rebuild grade column
    grade_list = table.column("grade").to_pylist()
    grade_list[row_idx] = grade
    new_grade = pa.array(grade_list, type=pa.string())

    # Rebuild tags column
    tags_list = table.column("tags").to_pylist()
    tags_list[row_idx] = tags
    new_tags = pa.array(tags_list, type=pa.list_(pa.string()))

    # Replace columns in-place (PyArrow tables are immutable; set_column returns new)
    grade_field_idx = table.schema.get_field_index("grade")
    tags_field_idx = table.schema.get_field_index("tags")

    table = table.set_column(
        grade_field_idx,
        pa.field("grade", pa.string(), nullable=True),
        new_grade,
    )
    table = table.set_column(
        tags_field_idx,
        pa.field("tags", pa.list_(pa.string()), nullable=True),
        new_tags,
    )
    return table


def _atomic_write(table: pa.Table, file_path: Path) -> None:
    """Write *table* to *file_path* atomically via a temp-file rename."""
    tmp_fd, tmp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")
    os.close(tmp_fd)
    try:
        pq.write_table(table, tmp_path)
        os.replace(tmp_path, file_path)
    except Exception:
        # Best-effort cleanup of the temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    logger.debug("Atomically wrote %s", file_path)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

episode_service = EpisodeService()
