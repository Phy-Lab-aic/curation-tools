from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    dataset_path: str = "/tmp/hf-mounts/Phy-lab/dataset"
    fastapi_port: int = 8000
    rerun_grpc_port: int = 9876
    rerun_web_port: int = 9090
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    model_config = {"env_prefix": "CURATION_"}


settings = Settings()
