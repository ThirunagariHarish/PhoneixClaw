"""Analyst agent API routes — persona management and signal feeds."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import desc, select

from apps.api.src.deps import DbSession
from shared.db.models.agent import Agent
from shared.db.models.trade_signal import TradeSignal

# Prefix is /api/v2 so paths below become:
#   GET  /api/v2/analyst/personas
#   POST /api/v2/agents/{agent_id}/analyst/run
#   GET  /api/v2/agents/{agent_id}/signals
#   GET  /api/v2/signals
router = APIRouter(prefix="/api/v2", tags=["analyst"])


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------

class PersonaResponse(BaseModel):
    id: str
    name: str
    emoji: str
    description: str
    min_confidence_threshold: int
    preferred_timeframes: list[str]
    stop_loss_style: str
    entry_style: str
    tool_weights: dict[str, float]


class AnalystSignalResponse(BaseModel):
    id: str
    agent_id: str
    ticker: str
    direction: Optional[str]
    decision: str
    confidence: Optional[int]
    analyst_persona: Optional[str]
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    risk_reward_ratio: Optional[float]
    pattern_name: Optional[str]
    reasoning: Optional[str]
    tool_signals_used: Optional[dict]
    created_at: str


class AnalystRunResponse(BaseModel):
    agent_id: str
    session_row_id: Optional[str]
    persona_id: str
    mode: str
    spawned: bool


class SpawnAnalystRequest(BaseModel):
    persona_id: str = "aggressive_momentum"
    mode: Literal["signal_intake", "pre_market"] = "signal_intake"
    tickers: list[str] = []
    since_minutes: int = 30
    chart_interval: str = "15m"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _require_auth(request: Request) -> str:
    """Return caller_id or raise 401."""
    caller_id = getattr(request.state, "user_id", None)
    if not caller_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return caller_id


def _check_ownership(agent: Agent, caller_id: str) -> None:
    """Raise 403 if the agent belongs to a different user."""
    if agent.user_id and str(agent.user_id) != caller_id:
        raise HTTPException(status_code=403, detail="Not your agent")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _signal_to_response(s: TradeSignal) -> AnalystSignalResponse:
    return AnalystSignalResponse(
        id=str(s.id),
        agent_id=str(s.agent_id),
        ticker=s.ticker,
        direction=s.direction,
        decision=s.decision,
        confidence=int(s.model_confidence * 100) if s.model_confidence is not None else None,
        analyst_persona=s.analyst_persona,
        entry_price=s.entry_price,
        stop_loss=s.stop_loss,
        take_profit=s.take_profit,
        risk_reward_ratio=s.risk_reward_ratio,
        pattern_name=s.pattern_name,
        reasoning=s.rejection_reason,
        tool_signals_used=s.tool_signals_used,
        created_at=s.created_at.isoformat() if s.created_at else "",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/analyst/personas", response_model=list[PersonaResponse])
async def list_personas() -> list[PersonaResponse]:
    """Return all available analyst agent personas. No auth required (public metadata)."""
    try:
        from agents.analyst.personas.library import PERSONA_LIBRARY
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"Persona library unavailable: {exc}")

    return [
        PersonaResponse(
            id=p.id,
            name=p.name,
            emoji=p.emoji,
            description=p.description,
            min_confidence_threshold=p.min_confidence_threshold,
            preferred_timeframes=p.preferred_timeframes,
            stop_loss_style=p.stop_loss_style,
            entry_style=p.entry_style,
            tool_weights=p.tool_weights,
        )
        for p in PERSONA_LIBRARY.values()
    ]


@router.post(
    "/agents/{agent_id}/analyst/run",
    response_model=AnalystRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_analyst_agent(
    agent_id: str,
    payload: SpawnAnalystRequest,
    request: Request,
    session: DbSession,
) -> AnalystRunResponse:
    """Spawn a persona-driven analyst agent session for an existing agent.

    Requires authentication. Caller must own the agent.
    Returns the session_row_id for tracking.
    """
    caller_id = _require_auth(request)

    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent_id")

    result = await session.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    _check_ownership(agent, caller_id)

    try:
        from agents.analyst.personas.library import PERSONA_LIBRARY
        if payload.persona_id not in PERSONA_LIBRARY:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown persona '{payload.persona_id}'. Available: {list(PERSONA_LIBRARY.keys())}",
            )
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"Persona library unavailable: {exc}")

    config = {
        **(agent.config or {}),
        "persona_id": payload.persona_id,
        "persona": payload.persona_id,
        "tickers": payload.tickers,
        "since_minutes": payload.since_minutes,
        "chart_interval": payload.chart_interval,
    }

    try:
        from apps.api.src.services.agent_gateway import gateway
        session_row_id = await gateway.create_analyst_agent(agent_uuid, config, mode=payload.mode)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to spawn analyst agent: {exc}")

    return AnalystRunResponse(
        agent_id=agent_id,
        session_row_id=session_row_id,
        persona_id=payload.persona_id,
        mode=payload.mode,
        spawned=True,
    )


@router.get("/agents/{agent_id}/signals", response_model=list[AnalystSignalResponse])
async def get_agent_signals(
    agent_id: str,
    request: Request,
    session: DbSession,
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(50, ge=1, le=500),
    decision: Optional[str] = None,
    ticker: Optional[str] = None,
) -> list[AnalystSignalResponse]:
    """List analyst signals for a specific agent.

    Requires authentication. Caller must own the agent.
    Filters to signal_source='analyst'.
    """
    caller_id = _require_auth(request)

    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent_id")

    result = await session.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    _check_ownership(agent, caller_id)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    q = (
        select(TradeSignal)
        .where(TradeSignal.agent_id == agent_uuid)
        .where(TradeSignal.signal_source == "analyst")
        .where(TradeSignal.created_at >= cutoff)
    )
    if decision:
        q = q.where(TradeSignal.decision == decision)
    if ticker:
        q = q.where(TradeSignal.ticker == ticker.upper())

    q = q.order_by(desc(TradeSignal.created_at)).limit(limit)
    signals_result = await session.execute(q)
    signals = signals_result.scalars().all()

    return [_signal_to_response(s) for s in signals]


@router.get("/signals", response_model=list[AnalystSignalResponse])
async def get_all_signals(
    request: Request,
    session: DbSession,
    agent_id: Optional[str] = Query(None),
    ticker: Optional[str] = Query(None),
    persona: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="ISO datetime string for cutoff"),
    signal_status: Optional[str] = Query(None, alias="status"),
    min_confidence: Optional[int] = Query(None, ge=0, le=100),
    limit: int = Query(100, le=500),
) -> list[AnalystSignalResponse]:
    """Global analyst signals feed across all agents owned by the caller.

    Requires authentication. Returns only signals from the caller's own agents.
    Query params: agent_id, ticker, persona, since, status, min_confidence, limit.
    """
    caller_id = _require_auth(request)

    # Resolve caller's agent UUIDs for ownership scoping
    try:
        import uuid as _uuid
        caller_uuid = _uuid.UUID(caller_id)
        owned_agents_q = select(Agent.id).where(Agent.user_id == caller_uuid)
        owned_result = await session.execute(owned_agents_q)
        owned_ids = [row[0] for row in owned_result.fetchall()]
    except (ValueError, AttributeError):
        owned_ids = []

    q = (
        select(TradeSignal)
        .where(TradeSignal.signal_source == "analyst")
    )

    # Scope to caller's agents (security: never return other users' signals)
    if owned_ids:
        q = q.where(TradeSignal.agent_id.in_(owned_ids))
    else:
        # No owned agents → empty result
        return []

    if agent_id:
        try:
            q = q.where(TradeSignal.agent_id == uuid.UUID(agent_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid agent_id filter")

    if ticker:
        q = q.where(TradeSignal.ticker == ticker.upper())

    if persona:
        q = q.where(TradeSignal.analyst_persona == persona)

    if since:
        try:
            cutoff_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            q = q.where(TradeSignal.created_at >= cutoff_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'since' datetime format")

    if signal_status:
        q = q.where(TradeSignal.decision == signal_status)

    if min_confidence is not None:
        # model_confidence is stored as 0.0–1.0
        q = q.where(TradeSignal.model_confidence >= min_confidence / 100.0)

    q = q.order_by(desc(TradeSignal.created_at)).limit(limit)
    signals_result = await session.execute(q)
    signals = signals_result.scalars().all()

    return [_signal_to_response(s) for s in signals]
