"""
OpenClaw Bridge Service — FastAPI app. M1.7.
Endpoints: /health, /heartbeat, /agents (CRUD), /skills/sync, /metrics.
"""
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi import FastAPI
from pydantic import BaseModel
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from src.config import settings
from src.auth import validate_bridge_token
from src.agent_manager import (
    create_agent,
    delete_agent,
    list_agents,
    get_agent,
    set_agent_status,
)

# Prometheus metrics
METRIC_HEARTBEAT_COUNT = Counter("phoenix_bridge_heartbeat_total", "Heartbeats served")
METRIC_AGENT_OPS = Counter("phoenix_bridge_agent_ops_total", "Agent operations", ["op"])
METRIC_ERRORS = Counter("phoenix_bridge_errors_total", "Errors", ["path"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Phoenix Bridge Service", version="1.0.0", lifespan=lifespan)

# Routes that require X-Bridge-Token
bridge_router = APIRouter(dependencies=[])


def require_token(x_bridge_token: str = Header(..., alias="X-Bridge-Token")):
    return validate_bridge_token(x_bridge_token)


class AgentCreate(BaseModel):
    name: str
    type: str = "trading"
    config: dict[str, Any] | None = None


class AgentMessage(BaseModel):
    body: dict[str, Any] | str


@app.get("/health")
async def health() -> dict:
    return {"status": "ready", "service": "phoenix-bridge"}


@app.get("/heartbeat")
async def heartbeat(_: str = Depends(require_token)) -> dict:
    METRIC_HEARTBEAT_COUNT.inc()
    from src.heartbeat import collect_heartbeat
    return collect_heartbeat()


@app.get("/agents")
async def agents_list(_: str = Depends(require_token)) -> dict:
    METRIC_AGENT_OPS.labels(op="list").inc()
    return {"agents": list_agents()}


@app.get("/agents/{agent_id}")
async def agent_get(agent_id: str, _: str = Depends(require_token)) -> dict:
    METRIC_AGENT_OPS.labels(op="get").inc()
    a = get_agent(agent_id)
    if not a:
        METRIC_ERRORS.labels(path="agent_get").inc()
        raise HTTPException(status_code=404, detail="Agent not found")
    return a


@app.post("/agents", status_code=201)
async def agent_create(
    payload: AgentCreate,
    _: str = Depends(require_token),
) -> dict:
    METRIC_AGENT_OPS.labels(op="create").inc()
    agent_id = payload.name.lower().replace(" ", "-")[:64]
    create_agent(agent_id, payload.name, payload.type, payload.config)
    return {"id": agent_id, "name": payload.name, "status": "CREATED"}


@app.put("/agents/{agent_id}")
async def agent_update(
    agent_id: str,
    payload: AgentCreate,
    _: str = Depends(require_token),
) -> dict:
    METRIC_AGENT_OPS.labels(op="update").inc()
    a = get_agent(agent_id)
    if not a:
        METRIC_ERRORS.labels(path="agent_update").inc()
        raise HTTPException(status_code=404, detail="Agent not found")
    set_agent_status(agent_id, "UPDATED")
    return {"id": agent_id, "name": payload.name, "status": "UPDATED"}


@app.delete("/agents/{agent_id}", status_code=204)
async def agent_delete(agent_id: str, _: str = Depends(require_token)) -> None:
    METRIC_AGENT_OPS.labels(op="delete").inc()
    delete_agent(agent_id)


@app.post("/agents/{agent_id}/pause")
async def agent_pause(agent_id: str, _: str = Depends(require_token)) -> dict:
    METRIC_AGENT_OPS.labels(op="pause").inc()
    a = get_agent(agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Agent not found")
    set_agent_status(agent_id, "PAUSED")
    return {"id": agent_id, "status": "PAUSED"}


@app.post("/agents/{agent_id}/resume")
async def agent_resume(agent_id: str, _: str = Depends(require_token)) -> dict:
    METRIC_AGENT_OPS.labels(op="resume").inc()
    a = get_agent(agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Agent not found")
    set_agent_status(agent_id, "RUNNING")
    return {"id": agent_id, "status": "RUNNING"}


@app.post("/agents/{agent_id}/message")
async def agent_message(
    agent_id: str,
    payload: AgentMessage,
    _: str = Depends(require_token),
) -> dict:
    a = get_agent(agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"id": agent_id, "received": True, "body": payload.body}


@app.post("/skills/sync")
async def skills_sync(_: str = Depends(require_token)) -> dict:
    from src.skill_sync import sync_skills
    return sync_skills()


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=18800,
        reload=os.environ.get("BRIDGE_DEBUG", "").lower() == "true",
    )
