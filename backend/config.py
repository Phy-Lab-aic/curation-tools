from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    dataset_path: str = "/data/datasets"
    allowed_dataset_roots: list[str] = [
        "/tmp/hf-mounts/Phy-lab/dataset",
        "/data/datasets",
    ]
    host: str = "127.0.0.1"
    fastapi_port: int = 8000
    rerun_grpc_port: int = 9876
    rerun_web_port: int = 9090
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    annotations_path: str = ""
    enable_rerun: bool = False
    debug: bool = False

    model_config = {"env_prefix": "CURATION_"}


settings = Settings()
