"""E2E tests for the curation tools UI using Playwright against a real running app.

Requires backend on :8000 and frontend on :5173.
"""

import json

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def browser_type_launch_args():
    return {"executable_path": "/snap/bin/chromium", "headless": True}


BASE_URL = "http://localhost:5173"

MOCK_CELL = {
    "name": "mock-cell",
    "path": "/mock/cell",
    "mount_root": "/mock",
    "active": True,
    "dataset_count": 1,
}

MOCK_DATASET = {
    "name": "broken-dataset",
    "path": "/mock/cell/broken-dataset",
    "robot_type": "testbot",
    "total_episodes": 3,
    "total_duration_sec": 15,
    "good_count": 0,
    "normal_count": 0,
    "bad_count": 0,
    "good_duration_sec": 0,
    "normal_duration_sec": 0,
    "bad_duration_sec": 0,
}


def _fulfill_json(route, payload, status: int = 200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _select_dataset(page: Page, name: str):
    """Click a dataset by its exact name text."""
    page.get_by_text(name, exact=True).click()


def _mock_dataset_load_failure(page: Page):
    requests = {"episodes": 0}

    def handler(route):
        url = route.request.url
        if url.endswith("/api/converter/status"):
            _fulfill_json(route, {
                "container_state": "stopped",
                "docker_available": False,
                "tasks": [],
                "summary": "",
            })
            return
        if url.endswith("/api/cells"):
            _fulfill_json(route, [MOCK_CELL])
            return
        if "/api/cells/" in url and url.endswith("/datasets"):
            _fulfill_json(route, [MOCK_DATASET])
            return
        if url.endswith("/api/datasets/load"):
            _fulfill_json(route, {"detail": "Dataset mount unavailable"}, status=500)
            return
        if url.endswith("/api/episodes"):
            requests["episodes"] += 1
            _fulfill_json(route, [])
            return
        route.continue_()

    page.route("**/api/**", handler)
    return requests


# ---------------------------------------------------------------------------
# Page load
# ---------------------------------------------------------------------------

class TestPageLoad:
    def test_app_loads(self, page: Page):
        page.goto(BASE_URL)
        expect(page.get_by_text("Datasets", exact=True)).to_be_visible()

    def test_shows_dataset_list(self, page: Page):
        page.goto(BASE_URL)
        expect(page.get_by_text("basic_aic_cheetcode_dataset", exact=True)).to_be_visible()
        expect(page.get_by_text("hojun", exact=True)).to_be_visible()

    def test_no_episodes_shown_initially(self, page: Page):
        page.goto(BASE_URL)
        # Before selecting a dataset, no episode list should be visible
        expect(page.get_by_text("#0", exact=True)).not_to_be_visible()


# ---------------------------------------------------------------------------
# Dataset selection
# ---------------------------------------------------------------------------

class TestDatasetSelection:
    def test_click_dataset_loads_it(self, page: Page):
        page.goto(BASE_URL)
        _select_dataset(page, "basic_aic_cheetcode_dataset")
        # Should show dataset info after loading
        expect(page.get_by_text("FPS")).to_be_visible(timeout=5000)
        expect(page.get_by_text("20", exact=True)).to_be_visible()

    def test_episode_list_populated_after_load(self, page: Page):
        page.goto(BASE_URL)
        _select_dataset(page, "basic_aic_cheetcode_dataset")
        # Wait for episodes to appear
        expect(page.get_by_text("#0", exact=True)).to_be_visible(timeout=5000)

    def test_switch_datasets(self, page: Page):
        page.goto(BASE_URL)
        _select_dataset(page, "basic_aic_cheetcode_dataset")
        expect(page.get_by_text("#0", exact=True)).to_be_visible(timeout=5000)

        # Switch to hojun
        _select_dataset(page, "hojun")
        page.wait_for_timeout(1000)
        expect(page.get_by_text("#0", exact=True)).to_be_visible()

    def test_dataset_load_failure_is_visible(self, page: Page):
        requests = _mock_dataset_load_failure(page)

        page.goto(BASE_URL)
        page.get_by_text("mock-cell", exact=True).click()
        _select_dataset(page, "broken-dataset")

        expect(page.get_by_text("Dataset mount unavailable", exact=True)).to_be_visible(timeout=5000)
        page.wait_for_timeout(300)
        assert requests["episodes"] == 0


# ---------------------------------------------------------------------------
# Episode interaction
# ---------------------------------------------------------------------------

class TestEpisodeInteraction:
    def test_click_episode_shows_editor(self, page: Page):
        page.goto(BASE_URL)
        _select_dataset(page, "basic_aic_cheetcode_dataset")
        expect(page.get_by_text("#0", exact=True)).to_be_visible(timeout=5000)
        page.get_by_text("#0", exact=True).click()
        # Right panel should show episode editor
        expect(page.get_by_text("Grade", exact=True)).to_be_visible(timeout=3000)

    def test_episode_shows_frame_count(self, page: Page):
        page.goto(BASE_URL)
        _select_dataset(page, "basic_aic_cheetcode_dataset")
        expect(page.get_by_text("#0", exact=True)).to_be_visible(timeout=5000)
        # Episodes should display frame counts
        expect(page.get_by_text("frames").first).to_be_visible()
