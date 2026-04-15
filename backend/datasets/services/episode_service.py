"""Service for reading and writing episode metadata in LeRobot v3.0 parquet files.

Episode base data is read from parquet files (read-only).
Grade/tags annotations are stored in SQLite (via backend.core.db).
Legacy JSON sidecar files are automatically migrated on first access.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import json as _json
import logging
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from backend.core.config import settings
from backend.core.db import get_db
from backend.datasets.schemas import Episode
from backend.datasets.services.dataset_service import dataset_service

logger = logging.getLogger(__name__)


class EpisodeNotFoundError(Exception):
    """Raised when an episode_index cannot be located in any parquet file."""


def _get_annotations_path() -> Path:
    """Return the directory for storing annotation sidecar files."""
    if settings.annotations_path:
        p = Path(settings.annotations_path)
    else:
        p = Path.home() / ".local" / "share" / "curation-tools" / "annotations"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sidecar_file(dataset_path: Path) -> Path:
    """Return the sidecar JSON path for a given dataset."""
    path_hash = hashlib.sha256(str(dataset_path.resolve()).encode()).hexdigest()[:16]
    name = f"{dataset_path.name}_{path_hash}.json"
    return _get_annotations_path() / name


def _load_sidecar_json(dataset_path: Path) -> dict[str, Any]:
    """Load the legacy sidecar JSON. Returns {episode_index_str: {grade, tags}}."""
    path = _sidecar_file(dataset_path)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt sidecar file %s, starting fresh", path)
    return {}


# Keep backward-compat alias so external callers (cell_service, export_service,
# distribution_service, test_mockup) that import _load_sidecar still work.
_load_sidecar = _load_sidecar_json


# ---------------------------------------------------------------------------
# DB helper functions
# ---------------------------------------------------------------------------


async def _get_dataset_id(dataset_path: Path) -> int | None:
    db = await get_db()
    async with db.execute("SELECT id FROM datasets WHERE path = ?", (str(dataset_path.resolve()),)) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else None


async def _ensure_dataset_registered(dataset_path: Path) -> int:
    db = await get_db()
    async with db.execute("SELECT id FROM datasets WHERE path = ?", (str(dataset_path.resolve()),)) as cursor:
        row = await cursor.fetchone()
    if row:
        return row[0]
    await db.execute("INSERT INTO datasets (path, name) VALUES (?, ?)", (str(dataset_path.resolve()), dataset_path.name))
    await db.commit()
    async with db.execute("SELECT id FROM datasets WHERE path = ?", (str(dataset_path.resolve()),)) as cursor:
        row = await cursor.fetchone()
    return row[0]


async def _ensure_migrated(dataset_id: int, dataset_path: Path) -> None:
    db = await get_db()
    async with db.execute("SELECT COUNT(*) FROM episode_annotations WHERE dataset_id = ?", (dataset_id,)) as cursor:
        count_row = await cursor.fetchone()
    if count_row[0] > 0:
        return
    sidecar = _load_sidecar_json(dataset_path)
    if not sidecar:
        return
    for idx_str, ann in sidecar.items():
        await db.execute(
            "INSERT OR IGNORE INTO episode_annotations (dataset_id, episode_index, grade, tags) VALUES (?, ?, ?, ?)",
            (dataset_id, int(idx_str), ann.get("grade"), _json.dumps(ann.get("tags", []))),
        )
    await db.commit()
    await _refresh_dataset_stats(dataset_id)
    logger.info("Migrated %d annotations from sidecar for %s", len(sidecar), dataset_path.name)


async def _load_annotations_from_db(dataset_id: int) -> dict[int, dict]:
    db = await get_db()
    async with db.execute("SELECT episode_index, grade, tags FROM episode_annotations WHERE dataset_id = ?", (dataset_id,)) as cursor:
        rows = await cursor.fetchall()
    return {
        row[0]: {"grade": row[1], "tags": _json.loads(row[2]) if row[2] else []}
        for row in rows
    }


async def _save_annotation_to_db(dataset_id: int, episode_index: int, grade: str | None, tags: list[str]) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO episode_annotations (dataset_id, episode_index, grade, tags, updated_at)
           VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
           ON CONFLICT(dataset_id, episode_index) DO UPDATE SET
             grade=excluded.grade, tags=excluded.tags, updated_at=excluded.updated_at""",
        (dataset_id, episode_index, grade, _json.dumps(tags)),
    )
    await db.commit()


async def _refresh_dataset_stats(dataset_id: int) -> None:
    db = await get_db()
    await db.execute(
        """INSERT INTO dataset_stats (dataset_id, graded_count, good_count, normal_count, bad_count, updated_at)
           VALUES (
             ?,
             (SELECT COUNT(grade) FROM episode_annotations WHERE dataset_id = ?),
             (SELECT SUM(CASE WHEN grade='good' THEN 1 ELSE 0 END) FROM episode_annotations WHERE dataset_id = ?),
             (SELECT SUM(CASE WHEN grade='normal' THEN 1 ELSE 0 END) FROM episode_annotations WHERE dataset_id = ?),
             (SELECT SUM(CASE WHEN grade='bad' THEN 1 ELSE 0 END) FROM episode_annotations WHERE dataset_id = ?),
             strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
           )
           ON CONFLICT(dataset_id) DO UPDATE SET
             graded_count=excluded.graded_count, good_count=excluded.good_count,
             normal_count=excluded.normal_count, bad_count=excluded.bad_count,
             updated_at=excluded.updated_at""",
        (dataset_id, dataset_id, dataset_id, dataset_id, dataset_id),
    )
    await db.commit()


class EpisodeService:
    """Reads episode base data from parquet, merges annotations from SQLite DB."""

    async def get_episodes(self) -> list[dict[str, Any]]:
        if dataset_service.episodes_cache is not None:
            return list(dataset_service.episodes_cache.values())

        episodes: dict[int, dict[str, Any]] = {}
        tasks_map = await dataset_service.get_tasks_map()

        dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
        await _ensure_migrated(dataset_id, dataset_service.dataset_path)
        annotations = await _load_annotations_from_db(dataset_id)

        for file_path in dataset_service.iter_episode_parquet_files():
            table = await asyncio.to_thread(pq.read_table, file_path)
            for row in _iter_rows(table):
                ep = _row_to_episode(row, tasks_map)
                # Merge DB annotations
                ann = annotations.get(ep["episode_index"])
                if ann:
                    ep["grade"] = ann.get("grade")
                    ep["tags"] = ann.get("tags", [])
                episodes[ep["episode_index"]] = ep

        dataset_service.episodes_cache = episodes
        return list(episodes.values())

    async def get_episode(self, episode_index: int) -> dict[str, Any]:
        if dataset_service.episodes_cache is not None:
            try:
                return dataset_service.episodes_cache[episode_index]
            except KeyError:
                raise EpisodeNotFoundError(
                    f"Episode {episode_index} not found in cache."
                )

        tasks_map = await dataset_service.get_tasks_map()
        file_path = dataset_service.get_file_for_episode(episode_index)
        if file_path is None:
            raise EpisodeNotFoundError(
                f"Episode {episode_index} not found in any parquet file."
            )

        dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
        await _ensure_migrated(dataset_id, dataset_service.dataset_path)
        annotations = await _load_annotations_from_db(dataset_id)

        table = await asyncio.to_thread(pq.read_table, file_path)

        for row in _iter_rows(table):
            if row.get("episode_index") == episode_index:
                ep = _row_to_episode(row, tasks_map)
                ann = annotations.get(episode_index)
                if ann:
                    ep["grade"] = ann.get("grade")
                    ep["tags"] = ann.get("tags", [])
                return ep

        raise EpisodeNotFoundError(
            f"Episode {episode_index} not found in {file_path}."
        )

    async def update_episode(
        self,
        episode_index: int,
        grade: str | None,
        tags: list[str],
    ) -> dict[str, Any]:
        """Persist grade and tags to the SQLite DB."""
        # Verify episode exists
        if dataset_service.episodes_cache is not None:
            if episode_index not in dataset_service.episodes_cache:
                raise EpisodeNotFoundError(
                    f"Episode {episode_index} not found."
                )
        else:
            file_path = dataset_service.get_file_for_episode(episode_index)
            if file_path is None:
                raise EpisodeNotFoundError(
                    f"Episode {episode_index} not found."
                )

        dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)
        await _save_annotation_to_db(dataset_id, episode_index, grade, tags)
        await _refresh_dataset_stats(dataset_id)

        # Invalidate distribution cache for annotation fields
        dataset_service.distribution_cache.pop("grade:auto", None)
        dataset_service.distribution_cache.pop("grade:bar", None)
        dataset_service.distribution_cache.pop("tags:auto", None)
        dataset_service.distribution_cache.pop("tags:bar", None)

        # Update cache
        if dataset_service.episodes_cache is not None:
            ep = dataset_service.episodes_cache.get(episode_index)
            if ep:
                ep["grade"] = grade
                ep["tags"] = tags
                return ep

        # Fallback: re-read the episode
        return await self.get_episode(episode_index)

    async def bulk_grade(
        self,
        episode_indices: list[int],
        grade: str,
    ) -> int:
        """Set grade for multiple episodes at once. Returns count updated."""
        dataset_id = await _ensure_dataset_registered(dataset_service.dataset_path)

        # Preserve existing tags when only updating grade
        existing_annotations = await _load_annotations_from_db(dataset_id)
        for idx in episode_indices:
            existing = existing_annotations.get(idx, {})
            tags = existing.get("tags", [])
            await _save_annotation_to_db(dataset_id, idx, grade, tags)
        await _refresh_dataset_stats(dataset_id)

        # Invalidate distribution cache
        dataset_service.distribution_cache.pop("grade:auto", None)
        dataset_service.distribution_cache.pop("grade:bar", None)
        dataset_service.distribution_cache.pop("tags:auto", None)
        dataset_service.distribution_cache.pop("tags:bar", None)

        # Update cache
        if dataset_service.episodes_cache is not None:
            for idx in episode_indices:
                ep = dataset_service.episodes_cache.get(idx)
                if ep:
                    ep["grade"] = grade

        return len(episode_indices)


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


def _parse_created_at(serial_number: Any) -> str | None:
    """Extract YYYY-MM-DD date from serial_number like '20260115_...'."""
    if serial_number is None:
        return None
    import re
    s = str(serial_number).strip().replace("-", "").replace("_", " ")
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", s)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def _row_to_episode(
    row: dict[str, Any],
    tasks_map: dict[int, str],
) -> dict[str, Any]:
    """Convert a raw parquet row dict into an Episode-compatible dict."""
    task_index: int = row.get("task_index", 0)
    task_instruction: str = tasks_map.get(task_index, "")

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
        created_at=_parse_created_at(row.get("serial_number")),
    ).model_dump()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

episode_service = EpisodeService()
