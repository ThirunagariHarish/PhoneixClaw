"""Pipeline Worker — FastAPI service for running ML-pipeline trading agents."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.pipeline_worker.src.config import settings
from services.pipeline_worker.src.worker_manager import WorkerManager
from shared.db.engine import get_engine, get_session_factory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [pipeline-worker] %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_manager: WorkerManager | None = None


def _get_manager() -> WorkerManager:
    if _manager is None:
        raise RuntimeError("WorkerManager not initialized")
    return _manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _manager
    logger.info("Pipeline Worker starting on port %d", settings.PIPELINE_WORKER_PORT)

    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    engine = get_engine()
    session_factory = get_session_factory(engine)

    _manager = WorkerManager(redis_client, session_factory)

    recovered = await _manager.recover_workers()
    logger.info("Startup complete — recovered %d workers", recovered)

    yield

    logger.info("Shutting down pipeline workers …")
    await _manager.shutdown()
    await redis_client.aclose()
    await engine.dispose()
    _manager = None
    logger.info("Pipeline Worker shut down")


app = FastAPI(
    title="Phoenix Pipeline Worker",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class StartWorkerRequest(BaseModel):
    agent_id: str
    connector_ids: list[str]
    config: dict = {}


class StartWorkerResponse(BaseModel):
    agent_id: str
    worker_id: str
    status: str
    stream_keys: list[str]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    mgr = _get_manager()
    return {"status": "ok", "workers_active": mgr.active_count}


@app.get("/workers")
async def list_workers():
    mgr = _get_manager()
    return {"workers": mgr.list_workers(), "total": mgr.active_count}


@app.get("/workers/{agent_id}")
async def get_worker(agent_id: str):
    mgr = _get_manager()
    worker = mgr.get_worker(agent_id)
    if not worker:
        raise HTTPException(status_code=404, detail=f"No active worker for agent {agent_id}")
    return worker


@app.post("/workers/start", response_model=StartWorkerResponse)
async def start_worker(req: StartWorkerRequest):
    mgr = _get_manager()
    try:
        result = await mgr.start_worker(req.agent_id, req.connector_ids, req.config)
        return StartWorkerResponse(**result)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc))


@app.post("/workers/{agent_id}/stop")
async def stop_worker(agent_id: str):
    mgr = _get_manager()
    stopped = await mgr.stop_worker(agent_id)
    if not stopped:
        raise HTTPException(status_code=404, detail=f"No active worker for agent {agent_id}")
    return {"agent_id": agent_id, "status": "stopped"}


if __name__ == "__main__":
    uvicorn.run(
        "services.pipeline_worker.src.main:app",
        host="0.0.0.0",
        port=settings.PIPELINE_WORKER_PORT,
        reload=False,
    )
