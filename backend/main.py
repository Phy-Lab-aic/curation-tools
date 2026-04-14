import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.routers import datasets, episodes, tasks, rerun, videos, scalars, dataset_ops, cells, distribution, fields
from backend.services import rerun_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.enable_rerun:
        try:
            rerun_service.init_rerun(
                grpc_port=settings.rerun_grpc_port,
                web_port=settings.rerun_web_port,
            )
            logger.info("Rerun viewer available at http://localhost:%d", settings.rerun_web_port)
        except Exception as e:
            logger.warning("Rerun init failed: %s (video player still works)", e)
    else:
        logger.info("Rerun disabled — using native video player")

    yield


app = FastAPI(
    title="robodata-studio",
    description="Internal curation and analytics tool for LeRobot datasets",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(datasets.router)
app.include_router(episodes.router)
app.include_router(tasks.router)
app.include_router(rerun.router)
app.include_router(videos.router)
app.include_router(scalars.router)
app.include_router(dataset_ops.router)
app.include_router(cells.router)
app.include_router(distribution.router)
app.include_router(fields.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


def start():
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.fastapi_port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    start()
