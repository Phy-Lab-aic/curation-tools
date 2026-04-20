from backend.core.config import Settings


def test_default_dataset_sources_build_allowed_roots():
    settings = Settings()

    assert settings.dataset_root_base == "/mnt/synology/data/data_div/2026_1"
    assert settings.dataset_sources == ["lerobot", "lerobot_test"]
    assert settings.allowed_dataset_roots == [
        "/mnt/synology/data/data_div/2026_1/lerobot",
        "/mnt/synology/data/data_div/2026_1/lerobot_test",
    ]
