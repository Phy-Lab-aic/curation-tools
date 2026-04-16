"""Tests for core/db.py — schema creation, connection lifecycle, version migration."""

import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from backend.core.db import get_db, init_db, close_db, _reset


@pytest_asyncio.fixture(autouse=True)
async def tmp_db(monkeypatch):
    """Point DB to a temp file for each test."""
    _reset()
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    yield tmp
    await close_db()
    _reset()
    tmp.unlink(missing_ok=True)


class TestInitDb:
    @pytest.mark.asyncio
    async def test_creates_tables(self, tmp_db):
        await init_db()
        db = await get_db()
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ) as cursor:
            tables = await cursor.fetchall()
        names = [t[0] for t in tables]
        assert "datasets" in names
        assert "episode_annotations" in names
        assert "dataset_stats" in names

    @pytest.mark.asyncio
    async def test_sets_user_version(self, tmp_db):
        await init_db()
        db = await get_db()
        async with db.execute("PRAGMA user_version") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 1

    @pytest.mark.asyncio
    async def test_idempotent(self, tmp_db):
        await init_db()
        await init_db()
        db = await get_db()
        async with db.execute("PRAGMA user_version") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 1


class TestGetDb:
    @pytest.mark.asyncio
    async def test_returns_same_connection(self, tmp_db):
        await init_db()
        db1 = await get_db()
        db2 = await get_db()
        assert db1 is db2

    @pytest.mark.asyncio
    async def test_close_and_reopen(self, tmp_db):
        await init_db()
        db1 = await get_db()
        await close_db()
        _reset()
        # Re-set the override since _reset clears it
        import backend.core.db
        backend.core.db._db_path_override = str(tmp_db)
        await init_db()
        db2 = await get_db()
        assert db1 is not db2


class TestSchema:
    @pytest.mark.asyncio
    async def test_datasets_table_columns(self, tmp_db):
        await init_db()
        db = await get_db()
        async with db.execute("PRAGMA table_info(datasets)") as cursor:
            rows = await cursor.fetchall()
        col_names = [r[1] for r in rows]
        for col in ["id", "path", "name", "cell_name", "fps", "total_episodes", "robot_type", "features", "synced_at"]:
            assert col in col_names

    @pytest.mark.asyncio
    async def test_episode_annotations_table_columns(self, tmp_db):
        await init_db()
        db = await get_db()
        async with db.execute("PRAGMA table_info(episode_annotations)") as cursor:
            rows = await cursor.fetchall()
        col_names = [r[1] for r in rows]
        for col in ["dataset_id", "episode_index", "grade", "tags"]:
            assert col in col_names

    @pytest.mark.asyncio
    async def test_grade_check_constraint(self, tmp_db):
        await init_db()
        db = await get_db()
        await db.execute("INSERT INTO datasets (path, name) VALUES (?, ?)", ("/tmp/test", "test"))
        await db.commit()
        with pytest.raises(Exception):
            await db.execute(
                "INSERT INTO episode_annotations (dataset_id, episode_index, grade) VALUES (1, 0, 'invalid')"
            )
            await db.commit()

    @pytest.mark.asyncio
    async def test_cascade_delete(self, tmp_db):
        await init_db()
        db = await get_db()
        await db.execute("INSERT INTO datasets (path, name) VALUES ('/tmp/x', 'x')")
        await db.execute("INSERT INTO episode_annotations (dataset_id, episode_index, grade) VALUES (1, 0, 'good')")
        await db.execute("INSERT INTO dataset_stats (dataset_id, good_count) VALUES (1, 1)")
        await db.commit()
        await db.execute("DELETE FROM datasets WHERE id = 1")
        await db.commit()
        async with db.execute("SELECT COUNT(*) FROM episode_annotations") as cursor:
            ann = await cursor.fetchone()
        async with db.execute("SELECT COUNT(*) FROM dataset_stats") as cursor:
            stats = await cursor.fetchone()
        assert ann[0] == 0
        assert stats[0] == 0
