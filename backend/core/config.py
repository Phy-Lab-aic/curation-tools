from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    dataset_path: str = "/mnt/synology/data/data_div/2026_1/lerobot"
    allowed_dataset_roots: list[str] = [
        "/mnt/synology/data/data_div/2026_1/lerobot",
    ]
    rosbag_to_lerobot_repo_path: str = "/home/tommoro/jm_ws/local_data_pipline/rosbag-to-lerobot"
    host: str = "127.0.0.1"
    fastapi_port: int = 8001
    rerun_grpc_port: int = 9876
    rerun_web_port: int = 9090
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    annotations_path: str = ""
    db_path: str = ""  # empty = default ~/.local/share/curation-tools/metadata.db
    enable_rerun: bool = False
    debug: bool = False
    cell_name_pattern: str = "cell*"

    model_config = {"env_prefix": "CURATION_"}


settings = Settings()
