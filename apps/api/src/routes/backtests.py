"""
Backtest API — run, list, and view backtest results.

M2.3: Backtesting pipeline API.
Reference: PRD Section 11.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.agent import Agent, AgentBacktest

router = APIRouter(prefix="/api/v2/backtests", tags=["backtests"])


class BacktestRequest(BaseModel):
    agent_id: str
    type: str = "signal_driven"
    config: dict[str, Any] = Field(default_factory=dict)
    date_range_start: str | None = None
    date_range_end: str | None = None
    initial_capital: float = 100000.0


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _backtest_to_dict(bt: AgentBacktest) -> dict:
    return {
        "id": str(bt.id),
        "agent_id": str(bt.agent_id),
        "status": bt.status,
        "strategy_template": bt.strategy_template,
        "start_date": bt.start_date.isoformat() if bt.start_date else None,
        "end_date": bt.end_date.isoformat() if bt.end_date else None,
        "parameters": bt.parameters or {},
        "metrics": bt.metrics or {},
        "equity_curve": bt.equity_curve or [],
        "total_trades": bt.total_trades,
        "win_rate": bt.win_rate,
        "sharpe_ratio": bt.sharpe_ratio,
        "max_drawdown": bt.max_drawdown,
        "total_return": bt.total_return,
        "error_message": bt.error_message,
        "completed_at": bt.completed_at.isoformat() if bt.completed_at else None,
        "created_at": bt.created_at.isoformat() if bt.created_at else None,
    }


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def start_backtest(payload: BacktestRequest, session: AsyncSession = Depends(get_session)):
    """Start a backtest run. Returns immediately with a run ID."""
    try:
        agent_uuid = uuid.UUID(payload.agent_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid agent_id") from e

    agent_row = await session.execute(select(Agent).where(Agent.id == agent_uuid))
    if not agent_row.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    run_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    parameters = {
        **(payload.config or {}),
        "type": payload.type,
        "initial_capital": payload.initial_capital,
    }
    backtest = AgentBacktest(
        id=run_id,
        agent_id=agent_uuid,
        status="RUNNING",
        strategy_template=payload.type,
        start_date=_parse_iso_datetime(payload.date_range_start),
        end_date=_parse_iso_datetime(payload.date_range_end),
        parameters=parameters,
        metrics={},
        equity_curve=[],
        created_at=now,
    )
    session.add(backtest)
    return {"id": str(run_id), "status": "RUNNING"}


@router.get("")
async def list_backtests(agent_id: str | None = None, session: AsyncSession = Depends(get_session)):
    """List backtest runs."""
    stmt = select(AgentBacktest).order_by(AgentBacktest.created_at.desc())
    if agent_id:
        try:
            aid = uuid.UUID(agent_id)
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid agent_id") from e
        stmt = stmt.where(AgentBacktest.agent_id == aid)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_backtest_to_dict(bt) for bt in rows]


@router.get("/{backtest_id}")
async def get_backtest(backtest_id: str, session: AsyncSession = Depends(get_session)):
    """Get backtest result details."""
    try:
        bid = uuid.UUID(backtest_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid backtest_id") from e
    result = await session.execute(select(AgentBacktest).where(AgentBacktest.id == bid))
    bt = result.scalar_one_or_none()
    if not bt:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return _backtest_to_dict(bt)
