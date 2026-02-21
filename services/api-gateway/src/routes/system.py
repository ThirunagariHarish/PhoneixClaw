import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.feature_flags import feature_flags
from shared.models.database import get_session
from shared.models.trade import Configuration
from shared.retention import get_retention_stats, purge_old_records

router = APIRouter(prefix="/api/v1/system", tags=["system"])

SERVICE_URLS = {
    "auth-service": "http://auth-service:8001/health",
    "trade-parser": "http://trade-parser:8006/health",
    "trade-gateway": "http://trade-gateway:8007/health",
    "trade-executor": "http://trade-executor:8008/health",
    "position-monitor": "http://position-monitor:8009/health",
    "notification-service": "http://notification-service:8010/health",
    "source-orchestrator": "http://source-orchestrator:8002/health",
    "nlp-parser": "http://nlp-parser:8020/health",
}


@router.get("/health")
async def system_health():
    services = {}
    async with httpx.AsyncClient(timeout=3) as client:
        for name, url in SERVICE_URLS.items():
            try:
                resp = await client.get(url)
                services[name] = "healthy" if resp.status_code == 200 else "unhealthy"
            except Exception:
                services[name] = "unreachable"
    services["api-gateway"] = "healthy"
    return {
        "services": services,
        "infrastructure": {
            "kafka": "healthy",
            "postgres": "healthy",
            "redis": "healthy",
        },
    }


@router.get("/config")
async def get_config(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = uuid.UUID(request.state.user_id)
    result = await session.execute(
        select(Configuration).where(Configuration.user_id == user_id)
    )
    configs = result.scalars().all()
    return {c.key: c.value for c in configs}


class ConfigUpdate(BaseModel):
    key: str
    value: dict | str | int | float | bool


@router.put("/config")
async def update_config(
    body: ConfigUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = uuid.UUID(request.state.user_id)
    result = await session.execute(
        select(Configuration).where(
            Configuration.user_id == user_id,
            Configuration.key == body.key,
        )
    )
    config_row = result.scalar_one_or_none()
    if config_row:
        config_row.value = body.value if isinstance(body.value, dict) else {"value": body.value}
        config_row.updated_by = "dashboard"
        config_row.updated_at = datetime.now(timezone.utc)
    else:
        config_row = Configuration(
            user_id=user_id,
            key=body.key,
            value=body.value if isinstance(body.value, dict) else {"value": body.value},
            updated_by="dashboard",
            updated_at=datetime.now(timezone.utc),
        )
        session.add(config_row)
    await session.commit()
    return {"key": body.key, "value": config_row.value}


@router.post("/kill-switch")
async def toggle_kill_switch(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Toggle the kill switch to disable/enable all trading."""
    user_id = uuid.UUID(request.state.user_id)
    result = await session.execute(
        select(Configuration).where(
            Configuration.user_id == user_id,
            Configuration.key == "enable_trading",
        )
    )
    config_row = result.scalar_one_or_none()
    if config_row:
        current = config_row.value.get("value", True) if isinstance(config_row.value, dict) else True
        new_value = not current
        config_row.value = {"value": new_value}
        config_row.updated_by = "kill-switch"
        config_row.updated_at = datetime.now(timezone.utc)
    else:
        new_value = False
        config_row = Configuration(
            user_id=user_id,
            key="enable_trading",
            value={"value": False},
            updated_by="kill-switch",
            updated_at=datetime.now(timezone.utc),
        )
        session.add(config_row)
    await session.commit()
    return {"kill_switch_active": not new_value, "enable_trading": new_value}


@router.get("/feature-flags")
async def get_feature_flags():
    return feature_flags.get_all()


class FeatureFlagUpdate(BaseModel):
    flag: str
    enabled: bool


@router.put("/feature-flags")
async def update_feature_flag(body: FeatureFlagUpdate, request: Request):
    feature_flags.set_flag(body.flag, body.enabled)
    return {"flag": body.flag, "enabled": body.enabled}


@router.get("/retention")
async def retention_stats():
    """Return data retention stats (row counts and oldest record per table)."""
    return await get_retention_stats()


@router.post("/retention/purge")
async def retention_purge(request: Request):
    """Manually trigger data retention purge."""
    results = await purge_old_records()
    return {"purged": results}
