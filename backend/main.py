import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.routers import datasets, episodes, tasks, rerun
from backend.services import rerun_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize Rerun viewer
    try:
        rerun_service.init_rerun(
            grpc_port=settings.rerun_grpc_port,
            web_port=settings.rerun_web_port,
        )
        logger.info("Rerun viewer available at http://localhost:%d", settings.rerun_web_port)
    except Exception as e:
        logger.warning("Failed to initialize Rerun: %s (visualization will be unavailable)", e)

    yield

    # Shutdown: nothing to clean up


app = FastAPI(
    title="LeRobot Curation Tools",
    description="Local curation tool for LeRobot datasets with Rerun visualization",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(datasets.router)
app.include_router(episodes.router)
app.include_router(tasks.router)
app.include_router(rerun.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


def start():
    """Entry point for pyproject.toml scripts."""
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=settings.fastapi_port,
        reload=True,
    )


if __name__ == "__main__":
    start()
