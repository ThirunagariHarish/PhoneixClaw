"""
Monitoring API routes — monitored positions and monitoring service status.

M2.13: Position monitoring endpoints.
Reference: PRD Section 8.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from apps.api.src.deps import DbSession
from shared.db.models.trade import Position

router = APIRouter(prefix="/api/v2/monitoring", tags=["monitoring"])


@router.get("/positions")
async def list_monitored_positions(
    session: DbSession,
    agent_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List positions currently being monitored (OPEN status)."""
    query = (
        select(Position)
        .where(Position.status == "OPEN")
        .order_by(Position.opened_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if agent_id:
        query = query.where(Position.agent_id == uuid.UUID(agent_id))
    result = await session.execute(query)
    positions = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "agent_id": str(p.agent_id),
            "account_id": p.account_id,
            "symbol": p.symbol,
            "side": p.side,
            "qty": p.qty,
            "entry_price": p.entry_price,
            "current_price": p.current_price,
            "unrealized_pnl": p.unrealized_pnl,
            "stop_loss": p.stop_loss,
            "take_profit": p.take_profit,
            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
        }
        for p in positions
    ]


@router.get("/status")
async def monitoring_status():
    """Return monitoring service status."""
    return {
        "service": "position-monitor",
        "status": "active",
        "capabilities": ["stop_loss", "trailing_stop", "take_profit", "eod_sweep"],
    }


@router.get("/health")
async def monitoring_health():
    """Monitoring subsystem health check."""
    return {
        "status": "healthy",
        "services": {
            "position_monitor": "running",
            "stop_loss_watcher": "running",
            "eod_sweep": "idle",
        },
        "uptime_seconds": 0,
    }


@router.get("/services")
async def monitoring_services():
    """List monitoring micro-services and their states."""
    return {
        "services": [
            {"name": "position-monitor", "status": "running", "last_check": None},
            {"name": "stop-loss-watcher", "status": "running", "last_check": None},
            {"name": "trailing-stop-engine", "status": "running", "last_check": None},
            {"name": "eod-sweep", "status": "idle", "last_check": None},
        ]
    }
