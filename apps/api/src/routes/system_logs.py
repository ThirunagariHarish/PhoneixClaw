"""Unified system logs API routes."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select, func

from apps.api.src.deps import DbSession
from shared.db.models.system_log import SystemLog

router = APIRouter(prefix="/api/v2/system-logs", tags=["system-logs"])


class LogCreate(BaseModel):
    source: str = Field(..., pattern="^(client|server|agent|backtest)$")
    level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARN|ERROR)$")
    service: str = Field(..., min_length=1, max_length=100)
    agent_id: str | None = None
    backtest_id: str | None = None
    message: str = Field(..., min_length=1)
    details: dict = Field(default_factory=dict)
    step: str | None = None
    progress_pct: int | None = Field(default=None, ge=0, le=100)


class LogBatchCreate(BaseModel):
    logs: list[LogCreate] = Field(..., min_length=1, max_length=100)


@router.post("", status_code=201)
async def create_log(payload: LogCreate, session: DbSession):
    """Create a single log entry."""
    log = SystemLog(
        id=uuid.uuid4(),
        source=payload.source,
        level=payload.level,
        service=payload.service,
        agent_id=payload.agent_id,
        backtest_id=payload.backtest_id,
        message=payload.message,
        details=payload.details,
        step=payload.step,
        progress_pct=payload.progress_pct,
    )
    session.add(log)
    await session.commit()
    return {"id": str(log.id)}


@router.post("/batch", status_code=201)
async def create_logs_batch(payload: LogBatchCreate, session: DbSession):
    """Create multiple log entries at once."""
    ids = []
    for entry in payload.logs:
        log = SystemLog(
            id=uuid.uuid4(),
            source=entry.source,
            level=entry.level,
            service=entry.service,
            agent_id=entry.agent_id,
            backtest_id=entry.backtest_id,
            message=entry.message,
            details=entry.details,
            step=entry.step,
            progress_pct=entry.progress_pct,
        )
        session.add(log)
        ids.append(str(log.id))
    await session.commit()
    return {"created": len(ids)}


@router.get("")
async def list_logs(
    session: DbSession,
    source: str | None = Query(None),
    level: str | None = Query(None),
    service: str | None = Query(None),
    agent_id: str | None = Query(None),
    backtest_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List logs with filtering."""
    query = select(SystemLog).order_by(desc(SystemLog.created_at))
    if source:
        query = query.where(SystemLog.source == source)
    if level:
        query = query.where(SystemLog.level == level)
    if service:
        query = query.where(SystemLog.service == service)
    if agent_id:
        query = query.where(SystemLog.agent_id == agent_id)
    if backtest_id:
        query = query.where(SystemLog.backtest_id == backtest_id)
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    logs = result.scalars().all()
    return [
        {
            "id": str(l.id),
            "source": l.source,
            "level": l.level,
            "service": l.service,
            "agent_id": l.agent_id,
            "backtest_id": l.backtest_id,
            "message": l.message,
            "details": l.details,
            "step": l.step,
            "progress_pct": l.progress_pct,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]


@router.get("/stats")
async def log_stats(session: DbSession):
    """Log statistics by source and level."""
    result = await session.execute(
        select(SystemLog.source, SystemLog.level, func.count(SystemLog.id))
        .group_by(SystemLog.source, SystemLog.level)
    )
    rows = result.all()
    stats = {}
    for source, level, count in rows:
        if source not in stats:
            stats[source] = {}
        stats[source][level] = count
    return stats
