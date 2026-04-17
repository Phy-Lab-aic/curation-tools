"""Tests for grade-reason feature: DB migration, service, router."""

import tempfile
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from backend.core.db import _reset, close_db, get_db, init_db


@pytest_asyncio.fixture(autouse=True)
async def tmp_db(monkeypatch):
    _reset()
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    monkeypatch.setattr("backend.core.db._db_path_override", str(tmp))
    yield tmp
    await close_db()
    _reset()
    tmp.unlink(missing_ok=True)


class TestMigrationV2:
    @pytest.mark.asyncio
    async def test_fresh_init_has_reason_column(self, tmp_db):
        await init_db()
        db = await get_db()
        async with db.execute("PRAGMA table_info(episode_annotations)") as cursor:
            rows = await cursor.fetchall()
        col_names = [r[1] for r in rows]
        assert "reason" in col_names

    @pytest.mark.asyncio
    async def test_user_version_is_2(self, tmp_db):
        await init_db()
        db = await get_db()
        async with db.execute("PRAGMA user_version") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 2

    @pytest.mark.asyncio
    async def test_v1_db_upgrades_in_place(self, tmp_db):
        # Build a v1 DB by hand
        async with aiosqlite.connect(str(tmp_db)) as conn:
            await conn.executescript("""
                CREATE TABLE datasets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL
                );
                CREATE TABLE episode_annotations (
                    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
                    episode_index INTEGER NOT NULL,
                    grade TEXT CHECK(grade IN ('good','normal','bad')),
                    tags TEXT DEFAULT '[]',
                    updated_at TEXT,
                    PRIMARY KEY (dataset_id, episode_index)
                );
                CREATE TABLE dataset_stats (dataset_id INTEGER PRIMARY KEY);
                INSERT INTO datasets (path, name) VALUES ('/tmp/x', 'x');
                INSERT INTO episode_annotations (dataset_id, episode_index, grade, tags)
                VALUES (1, 0, 'bad', '[]');
                PRAGMA user_version = 1;
            """)
            await conn.commit()

        # Now run init_db — it should upgrade
        await init_db()
        db = await get_db()
        async with db.execute("PRAGMA user_version") as cursor:
            row = await cursor.fetchone()
        assert row[0] == 2
        async with db.execute("PRAGMA table_info(episode_annotations)") as cursor:
            rows = await cursor.fetchall()
        assert "reason" in [r[1] for r in rows]
        # Pre-existing row preserved with NULL reason
        async with db.execute(
            "SELECT grade, reason FROM episode_annotations WHERE dataset_id=1 AND episode_index=0"
        ) as cursor:
            row = await cursor.fetchone()
        assert row[0] == "bad"
        assert row[1] is None


class TestSchemas:
    def test_episode_response_includes_reason(self):
        from backend.datasets.schemas import Episode
        ep = Episode(
            episode_index=0, length=100, task_index=0,
            dataset_from_index=0, dataset_to_index=100,
            grade="bad", reason="camera shake",
        )
        assert ep.reason == "camera shake"
        assert ep.model_dump()["reason"] == "camera shake"

    def test_episode_response_default_reason_is_none(self):
        from backend.datasets.schemas import Episode
        ep = Episode(episode_index=0, length=0, task_index=0)
        assert ep.reason is None

    def test_update_requires_reason_for_bad(self):
        from pydantic import ValidationError

        from backend.datasets.schemas import EpisodeUpdate
        with pytest.raises(ValidationError):
            EpisodeUpdate(grade="bad", tags=[])
        with pytest.raises(ValidationError):
            EpisodeUpdate(grade="bad", tags=[], reason="   ")
        # Non-empty reason is fine
        EpisodeUpdate(grade="bad", tags=[], reason="too dark")

    def test_update_requires_reason_for_normal(self):
        from pydantic import ValidationError

        from backend.datasets.schemas import EpisodeUpdate
        with pytest.raises(ValidationError):
            EpisodeUpdate(grade="normal", tags=[])
        EpisodeUpdate(grade="normal", tags=[], reason="acceptable but slow")

    def test_update_good_does_not_require_reason(self):
        from backend.datasets.schemas import EpisodeUpdate
        u = EpisodeUpdate(grade="good", tags=[])
        assert u.reason is None

    def test_update_good_clears_reason_when_provided(self):
        # Reason supplied with grade=good should be allowed but ignored downstream;
        # at the schema level we accept it (service layer will null it out).
        from backend.datasets.schemas import EpisodeUpdate
        u = EpisodeUpdate(grade="good", tags=[], reason="ignored")
        assert u.grade == "good"

    def test_bulk_grade_requires_reason_for_bad(self):
        from pydantic import ValidationError

        from backend.datasets.schemas import BulkGradeRequest
        with pytest.raises(ValidationError):
            BulkGradeRequest(episode_indices=[0, 1], grade="bad")
        BulkGradeRequest(episode_indices=[0, 1], grade="bad", reason="bad batch")

    def test_bulk_grade_good_does_not_require_reason(self):
        from backend.datasets.schemas import BulkGradeRequest
        BulkGradeRequest(episode_indices=[0], grade="good")
