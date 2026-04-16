"""Tests for converter_service — log parsing and status logic."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.converter.service import (
    TaskProgress,
    ConverterStatus,
    parse_progress,
    get_status,
    _ROW_RE,
    _TOTAL_RE,
)


# ---------------------------------------------------------------------------
# Fixtures: sample log output from auto_converter
# ---------------------------------------------------------------------------

SCAN_TABLE_LOG = """\
2026-04-15 10:23:01 [INFO] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026-04-15 10:23:01 [INFO]   Scan Cycle 42                                    2026-04-15 10:23
2026-04-15 10:23:01 [INFO] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026-04-15 10:23:01 [INFO]   Cell/Task                              Total   Done  Pending  Fail Retry
2026-04-15 10:23:01 [INFO]   ──────────────────────────────────────────────────────────────────────────────
2026-04-15 10:23:01 [INFO]   cell_a/task_1                             12      8        3     1     0
2026-04-15 10:23:01 [INFO]   cell_a/task_2                              5      5        0     0     0
2026-04-15 10:23:01 [INFO]   cell_b/pick_place                         8      3        4     1     2
2026-04-15 10:23:01 [INFO] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
2026-04-15 10:23:01 [INFO]   Total: 3 tasks | 25 recordings | 16 done | 7 pending | 2 failed
2026-04-15 10:23:01 [INFO] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

EMPTY_LOG = """\
2026-04-15 10:23:01 [INFO] No new recordings to convert
2026-04-15 10:23:01 [INFO] Waiting 60s before next scan...
"""

NO_OUTPUT = ""


# ---------------------------------------------------------------------------
# parse_progress tests
# ---------------------------------------------------------------------------

class TestParseProgress:
    """Test log parsing logic by mocking _run to return canned log output."""

    @pytest.mark.asyncio
    async def test_parses_scan_table_rows(self):
        """Should extract 3 task rows from a well-formed scan table."""
        with patch("backend.converter.service._run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, SCAN_TABLE_LOG, "")
            tasks, summary = await parse_progress()

        assert len(tasks) == 3
        assert tasks[0] == TaskProgress("cell_a/task_1", 12, 8, 3, 1, 0)
        assert tasks[1] == TaskProgress("cell_a/task_2", 5, 5, 0, 0, 0)
        assert tasks[2] == TaskProgress("cell_b/pick_place", 8, 3, 4, 1, 2)

    @pytest.mark.asyncio
    async def test_parses_summary_line(self):
        """Should extract the Total summary line."""
        with patch("backend.converter.service._run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, SCAN_TABLE_LOG, "")
            tasks, summary = await parse_progress()

        assert "3 tasks" in summary
        assert "25 recordings" in summary
        assert "16 done" in summary

    @pytest.mark.asyncio
    async def test_empty_log_returns_empty(self):
        """No scan table in log → empty results."""
        with patch("backend.converter.service._run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, EMPTY_LOG, "")
            tasks, summary = await parse_progress()

        assert tasks == []
        assert summary == ""

    @pytest.mark.asyncio
    async def test_no_output_returns_empty(self):
        """Empty log output → empty results."""
        with patch("backend.converter.service._run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (0, NO_OUTPUT, "")
            tasks, summary = await parse_progress()

        assert tasks == []
        assert summary == ""

    @pytest.mark.asyncio
    async def test_docker_error_returns_empty(self):
        """docker logs failure → empty results."""
        with patch("backend.converter.service._run", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = (1, "", "container not found")
            tasks, summary = await parse_progress()

        assert tasks == []
        assert summary == ""


# ---------------------------------------------------------------------------
# Regex unit tests
# ---------------------------------------------------------------------------

class TestRegexPatterns:
    def test_row_regex_matches_typical_line(self):
        line = "  cell_a/task_1                             12      8        3     1     0"
        m = _ROW_RE.match(line)
        assert m is not None
        assert m.group(1).strip() == "cell_a/task_1"
        assert int(m.group(2)) == 12
        assert int(m.group(3)) == 8

    def test_row_regex_no_match_on_header(self):
        line = "  Cell/Task                              Total   Done  Pending  Fail Retry"
        m = _ROW_RE.match(line)
        assert m is None  # "Total" is not a number

    def test_total_regex_matches(self):
        line = "  Total: 3 tasks | 25 recordings | 16 done | 7 pending | 2 failed"
        m = _TOTAL_RE.search(line)
        assert m is not None
        assert int(m.group(1)) == 3   # tasks
        assert int(m.group(2)) == 25  # recordings
        assert int(m.group(3)) == 16  # done
        assert int(m.group(4)) == 7   # pending
        assert int(m.group(5)) == 2   # failed


# ---------------------------------------------------------------------------
# get_status tests
# ---------------------------------------------------------------------------

class TestGetStatus:
    @pytest.mark.asyncio
    async def test_docker_unavailable(self):
        with patch("backend.converter.service.check_docker", new_callable=AsyncMock, return_value=False):
            status = await get_status()

        assert status.docker_available is False
        assert status.container_state == "unknown"

    @pytest.mark.asyncio
    async def test_stopped_container(self):
        with patch("backend.converter.service.check_docker", new_callable=AsyncMock, return_value=True), \
             patch("backend.converter.service.get_container_state", new_callable=AsyncMock, return_value="stopped"):
            status = await get_status()

        assert status.docker_available is True
        assert status.container_state == "stopped"
        assert status.tasks == []

    @pytest.mark.asyncio
    async def test_running_container_fetches_progress(self):
        fake_tasks = [TaskProgress("a/b", 10, 5, 3, 2, 0)]
        with patch("backend.converter.service.check_docker", new_callable=AsyncMock, return_value=True), \
             patch("backend.converter.service.get_container_state", new_callable=AsyncMock, return_value="running"), \
             patch("backend.converter.service.parse_progress", new_callable=AsyncMock, return_value=(fake_tasks, "Total: 1 task")):
            status = await get_status()

        assert status.container_state == "running"
        assert len(status.tasks) == 1
        assert status.tasks[0].cell_task == "a/b"

    @pytest.mark.asyncio
    async def test_building_state(self):
        import backend.converter.service as svc
        # Simulate the lock being held by acquiring it
        await svc._build_lock.acquire()
        try:
            with patch("backend.converter.service.check_docker", new_callable=AsyncMock, return_value=True):
                status = await get_status()
            assert status.container_state == "building"
        finally:
            svc._build_lock.release()
