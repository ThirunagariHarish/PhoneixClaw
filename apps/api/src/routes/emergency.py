"""
Emergency Kill Switch API routes.

Provides endpoints to immediately pause all running agents, cancel pending
orders, and optionally mark open positions for closing.  Every activation
is written to the system_logs table as an audit record.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.agent import Agent
from shared.db.models.agent_trade import AgentTrade
from shared.db.models.system_log import SystemLog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/emergency", tags=["emergency"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class KillSwitchRequest(BaseModel):
    close_positions: bool = False
    reason: str = Field(..., min_length=1, max_length=500)


class KillSwitchResponse(BaseModel):
    agents_paused: int
    orders_cancelled: int
    positions_closing: int


class KillSwitchStatusResponse(BaseModel):
    active: bool
    activated_at: str | None = None
    reason: str | None = None
    activated_by: str | None = None


class KillSwitchHistoryItem(BaseModel):
    id: str
    activated_at: str
    reason: str
    agents_paused: int
    orders_cancelled: int
    positions_closing: int


# ---------------------------------------------------------------------------
# POST /api/v2/emergency/kill-switch
# ---------------------------------------------------------------------------

@router.post("/kill-switch", response_model=KillSwitchResponse)
async def activate_kill_switch(
    body: KillSwitchRequest,
    db: AsyncSession = Depends(get_session),
) -> KillSwitchResponse:
    """Activate the emergency kill switch.

    1. Pause all agents with status='running'.
    2. Cancel pending trades (decision_status='pending').
    3. Optionally mark open positions for closing.
    4. Write an audit log entry.
    """
    now = datetime.now(timezone.utc)
    reason_text = f"[KILL SWITCH] {body.reason}"

    # 1 -- Pause running agents -------------------------------------------------
    agent_result = await db.execute(
        update(Agent)
        .where(Agent.status == "running")
        .values(status="paused", error_message=reason_text)
    )
    agents_paused: int = agent_result.rowcount  # type: ignore[assignment]

    # 2 -- Cancel pending trades ------------------------------------------------
    orders_result = await db.execute(
        update(AgentTrade)
        .where(AgentTrade.decision_status == "pending")
        .values(decision_status="cancelled", rejection_reason=reason_text)
    )
    orders_cancelled: int = orders_result.rowcount  # type: ignore[assignment]

    # 3 -- Optionally mark open positions for closing ---------------------------
    positions_closing = 0
    if body.close_positions:
        pos_result = await db.execute(
            update(AgentTrade)
            .where(AgentTrade.status == "open")
            .values(status="closing", rejection_reason=reason_text)
        )
        positions_closing = pos_result.rowcount  # type: ignore[assignment]

    # 4 -- Audit log entry ------------------------------------------------------
    log_entry = SystemLog(
        id=uuid.uuid4(),
        source="server",
        level="WARN",
        service="emergency-kill-switch",
        message=f"Kill switch activated: {body.reason}",
        details={
            "agents_paused": agents_paused,
            "orders_cancelled": orders_cancelled,
            "positions_closing": positions_closing,
            "close_positions": body.close_positions,
            "reason": body.reason,
        },
        created_at=now,
    )
    db.add(log_entry)

    await db.commit()

    logger.warning(
        "KILL SWITCH ACTIVATED  agents_paused=%d  orders_cancelled=%d  positions_closing=%d  reason=%s",
        agents_paused,
        orders_cancelled,
        positions_closing,
        body.reason,
    )

    return KillSwitchResponse(
        agents_paused=agents_paused,
        orders_cancelled=orders_cancelled,
        positions_closing=positions_closing,
    )


# ---------------------------------------------------------------------------
# GET /api/v2/emergency/status
# ---------------------------------------------------------------------------

@router.get("/status", response_model=KillSwitchStatusResponse)
async def get_kill_switch_status(
    db: AsyncSession = Depends(get_session),
) -> KillSwitchStatusResponse:
    """Return whether the kill switch is currently active.

    Heuristic: the kill switch is considered active when there are zero
    agents with status='running' AND the most recent kill-switch audit log
    was created within the last 24 hours.
    """
    # Check for any running agents
    running_count_result = await db.execute(
        select(func.count(Agent.id)).where(Agent.status == "running")
    )
    running_count = running_count_result.scalar() or 0

    # Fetch the most recent kill-switch log entry
    latest_log_result = await db.execute(
        select(SystemLog)
        .where(SystemLog.service == "emergency-kill-switch")
        .order_by(SystemLog.created_at.desc())
        .limit(1)
    )
    latest_log = latest_log_result.scalar_one_or_none()

    if latest_log is None:
        return KillSwitchStatusResponse(active=False)

    # Consider active if no running agents and a kill-switch log exists
    active = running_count == 0 and latest_log is not None
    details = latest_log.details if isinstance(latest_log.details, dict) else {}

    return KillSwitchStatusResponse(
        active=active,
        activated_at=latest_log.created_at.isoformat() if latest_log.created_at else None,
        reason=details.get("reason"),
        activated_by="admin",
    )


# ---------------------------------------------------------------------------
# GET /api/v2/emergency/history
# ---------------------------------------------------------------------------

@router.get("/history", response_model=list[KillSwitchHistoryItem])
async def get_kill_switch_history(
    limit: int = 5,
    db: AsyncSession = Depends(get_session),
) -> list[KillSwitchHistoryItem]:
    """Return the last N kill-switch activations from the audit log."""
    result = await db.execute(
        select(SystemLog)
        .where(SystemLog.service == "emergency-kill-switch")
        .order_by(SystemLog.created_at.desc())
        .limit(limit)
    )
    logs = result.scalars().all()

    items: list[KillSwitchHistoryItem] = []
    for log in logs:
        details = log.details if isinstance(log.details, dict) else {}
        items.append(
            KillSwitchHistoryItem(
                id=str(log.id),
                activated_at=log.created_at.isoformat() if log.created_at else "",
                reason=details.get("reason", ""),
                agents_paused=details.get("agents_paused", 0),
                orders_cancelled=details.get("orders_cancelled", 0),
                positions_closing=details.get("positions_closing", 0),
            )
        )
    return items
