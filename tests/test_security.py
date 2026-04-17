"""Tests for path traversal security in dataset_service.load_dataset()."""

import pytest
from backend.services.dataset_service import DatasetService
from backend.core.config import settings


@pytest.fixture
def service():
    """Fresh DatasetService instance for each test."""
    return DatasetService()


class TestPathTraversalSecurity:
    """Verify allowed_dataset_roots validation blocks path traversal attacks."""

    def test_path_traversal_with_dot_dot(self, service):
        """../  sequences that escape the allowed root must be rejected."""
        with pytest.raises(ValueError, match="not under any allowed root"):
            service.load_dataset("/tmp/hf-mounts/../../etc/passwd")

    def test_absolute_path_outside_allowed_roots(self, service):
        """Absolute paths outside allowed roots must be rejected."""
        with pytest.raises(ValueError, match="not under any allowed root"):
            service.load_dataset("/etc/passwd")

    def test_allowed_root_substring_not_sufficient(self, service):
        """A path whose string starts with an allowed root but is not under it must be rejected.

        e.g. /tmp/hf-mounts-evil/dataset starts with "/tmp/hf-mounts" as a string
        but is NOT a child directory. The check uses Path.parents, not startswith.
        """
        with pytest.raises(ValueError, match="not under any allowed root"):
            service.load_dataset("/tmp/hf-mounts-evil/dataset")

    def test_valid_path_under_allowed_root(self, service, tmp_path, monkeypatch):
        """A path under an allowed root should pass the path validation.

        It may raise FileNotFoundError because the directory doesn't exist,
        but it must NOT raise ValueError for the path check.
        """
        monkeypatch.setattr(
            settings,
            "allowed_dataset_roots",
            settings.allowed_dataset_roots + [str(tmp_path)],
        )

        with pytest.raises(FileNotFoundError):
            service.load_dataset(tmp_path / "valid-dataset")

    def test_file_under_allowed_root_still_raises_directory_error(self, service, tmp_path, monkeypatch):
        """An existing non-directory under an allowed root should keep its current error."""
        dataset_file = tmp_path / "dataset.txt"
        dataset_file.write_text("not a dataset", encoding="utf-8")
        monkeypatch.setattr(
            settings,
            "allowed_dataset_roots",
            settings.allowed_dataset_roots + [str(tmp_path)],
        )

        with pytest.raises(ValueError, match="not a directory"):
            service.load_dataset(dataset_file)

    def test_empty_path(self, service):
        """An empty path resolves to cwd, which should not be under allowed roots."""
        with pytest.raises((ValueError, FileNotFoundError)):
            service.load_dataset("")
