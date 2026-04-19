"""
Strategy CRUD API — 50 strategy templates, DB persistence, agent auto-creation.

M2.6: Strategy agent management.
Reference: PRD Section 3.5, strategy_wizard_redesign plan.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, desc

from apps.api.src.deps import DbSession
from apps.api.src.data.strategy_templates import (
    STRATEGY_TEMPLATES,
    STRATEGY_TEMPLATES_BY_ID,
    STRATEGY_CATEGORIES_WITH_COUNTS,
)
from shared.db.models.agent import Agent
from shared.db.models.strategy import Strategy

router = APIRouter(prefix="/api/v2/strategies", tags=["strategies"])


class StrategyCreate(BaseModel):
    template_id: str
    name: str = Field("", max_length=150)
    symbol: str = "SPY"
    config: dict[str, Any] = Field(default_factory=dict)
    legs: list[dict[str, Any]] = Field(default_factory=list)
    backtest_params: dict[str, Any] = Field(default_factory=dict)
    skills_required: list[str] = Field(default_factory=list)
    instance_id: str = ""
    agent_name: str = ""
    agent_role_description: str = ""


class StrategyResponse(BaseModel):
    id: str
    name: str
    template_id: str
    symbol: str
    category: str | None
    description: str | None
    status: str
    config: dict[str, Any]
    legs: list[dict[str, Any]]
    backtest_params: dict[str, Any]
    skills_required: list[str]
    agent_id: str | None
    backtest_pnl: float | None
    backtest_sharpe: float | None
    win_rate: float | None
    max_drawdown: float | None
    total_trades: int | None
    created_at: str

    @classmethod
    def from_model(cls, s: Strategy) -> "StrategyResponse":
        return cls(
            id=str(s.id),
            name=s.name,
            template_id=s.template_id,
            symbol=s.symbol,
            category=s.category,
            description=s.description,
            status=s.status,
            config=s.config or {},
            legs=s.legs if isinstance(s.legs, list) else [],
            backtest_params=s.backtest_params or {},
            skills_required=s.skills_required if isinstance(s.skills_required, list) else [],
            agent_id=str(s.agent_id) if s.agent_id else None,
            backtest_pnl=s.backtest_pnl,
            backtest_sharpe=s.backtest_sharpe,
            win_rate=s.win_rate,
            max_drawdown=s.max_drawdown,
            total_trades=s.total_trades,
            created_at=s.created_at.isoformat() if s.created_at else "",
        )


@router.get("/templates")
async def list_templates():
    """Return all 50 strategy templates with category metadata."""
    return {
        "templates": STRATEGY_TEMPLATES,
        "categories": STRATEGY_CATEGORIES_WITH_COUNTS,
    }


@router.get("/templates/{template_id}")
async def get_template(template_id: str):
    """Return a single template by ID."""
    tpl = STRATEGY_TEMPLATES_BY_ID.get(template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    return tpl


@router.get("", response_model=list[StrategyResponse])
async def list_strategies(
    session: DbSession,
    category: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List persisted strategies with optional filters."""
    query = select(Strategy).order_by(desc(Strategy.created_at))
    if category:
        query = query.where(Strategy.category == category)
    if status_filter:
        query = query.where(Strategy.status == status_filter)
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    return [StrategyResponse.from_model(s) for s in result.scalars().all()]


@router.get("/{strategy_id}", response_model=StrategyResponse)
async def get_strategy(strategy_id: str, session: DbSession):
    result = await session.execute(
        select(Strategy).where(Strategy.id == uuid.UUID(strategy_id))
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return StrategyResponse.from_model(strategy)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=StrategyResponse)
async def create_strategy(payload: StrategyCreate, session: DbSession):
    """
    Create strategy + auto-create linked agent.

    1. Validate template exists
    2. Merge template defaults with user overrides
    3. Create Agent in DB (type=strategy, status=BACKTESTING)
    4. Create Strategy in DB linked to that agent
    """
    template = STRATEGY_TEMPLATES_BY_ID.get(payload.template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    strategy_name = payload.name or template["name"]
    symbol = payload.symbol or template.get("default_symbol", "SPY")

    merged_config = {**template.get("default_config", {}), **payload.config}
    merged_legs = payload.legs if payload.legs else template.get("legs", [])
    merged_backtest = {**template.get("backtest_params", {}), **payload.backtest_params}
    merged_skills = payload.skills_required if payload.skills_required else template.get("skills_required", [])

    if not payload.instance_id:
        raise HTTPException(
            status_code=400,
            detail="instance_id is required",
        )

    agent_name = payload.agent_name or f"{strategy_name} Agent"
    agent = Agent(
        id=uuid.uuid4(),
        name=agent_name,
        type="strategy",
        status="BACKTESTING",
        instance_id=uuid.UUID(payload.instance_id),
        config={
            "strategy_template_id": payload.template_id,
            "symbol": symbol,
            "description": payload.agent_role_description or template.get("description", ""),
            "skills": merged_skills,
            "entry_rules": merged_config,
            "backtest_params": merged_backtest,
            "legs": merged_legs,
        },
    )
    session.add(agent)
    await session.flush()

    strategy = Strategy(
        id=uuid.uuid4(),
        name=strategy_name,
        template_id=payload.template_id,
        symbol=symbol,
        category=template.get("category"),
        description=template.get("description"),
        config=merged_config,
        legs=merged_legs,
        backtest_params=merged_backtest,
        skills_required=merged_skills,
        agent_id=agent.id,
        status="BACKTESTING",
    )
    session.add(strategy)
    await session.commit()
    await session.refresh(strategy)

    return StrategyResponse.from_model(strategy)


@router.delete("/{strategy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_strategy(strategy_id: str, session: DbSession):
    result = await session.execute(
        select(Strategy).where(Strategy.id == uuid.UUID(strategy_id))
    )
    strategy = result.scalar_one_or_none()
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    await session.delete(strategy)
    await session.commit()
