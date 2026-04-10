"""
Agent CRUD API routes — V3 Cloud-First Architecture.

Agents are created via the wizard, backtested locally (or via Claude Code
Cloud Tasks), and promoted to Docker-managed trading workers.  All state
lives in PostgreSQL; no SSH or VPS management.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc

from apps.api.src.deps import DbSession
from shared.db.models.agent import Agent, AgentBacktest
from shared.db.models.connector import Connector, ConnectorAgent

router = APIRouter(prefix="/api/v2/agents", tags=["agents"])


class AgentCreate(BaseModel):
    """Agent creation wizard payload."""
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern="^(trading|trend|sentiment|analyst)$")
    config: dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    data_source: str = ""
    skills: list[str] = Field(default_factory=list)
    connector_ids: list[str] = Field(default_factory=list)


class AgentUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    config: dict[str, Any] | None = None


class AgentResponse(BaseModel):
    id: str
    name: str
    type: str
    status: str
    worker_status: str = "STOPPED"
    runtime_status: str = "unknown"  # P4: derived from last_activity_at / heartbeat age
    config: dict[str, Any]
    channel_name: str | None = None
    analyst_name: str | None = None
    model_type: str | None = None
    model_accuracy: float | None = None
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    current_mode: str = "conservative"
    rules_version: int = 1
    last_signal_at: str | None = None
    last_trade_at: str | None = None
    created_at: str
    error_message: str | None = None

    @staticmethod
    def _derive_runtime_status(a: Agent) -> str:
        """P4: 'alive' if heartbeat within 3min, 'stale' if older, else 'stopped'."""
        last = getattr(a, "last_activity_at", None)
        if not last:
            return "stopped"
        try:
            now = datetime.now(timezone.utc)
            # naive → assume UTC
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            age = (now - last).total_seconds()
            if age < 180:
                return "alive"
            if age < 900:
                return "stale"
            return "stopped"
        except Exception:
            return "unknown"

    @classmethod
    def from_model(cls, a: Agent) -> "AgentResponse":
        return cls(
            id=str(a.id),
            name=a.name,
            type=a.type,
            status=a.status,
            worker_status=a.worker_status or "STOPPED",
            runtime_status=cls._derive_runtime_status(a),
            config=a.config or {},
            channel_name=a.channel_name,
            analyst_name=a.analyst_name,
            model_type=a.model_type,
            model_accuracy=a.model_accuracy,
            daily_pnl=a.daily_pnl or 0.0,
            total_pnl=a.total_pnl or 0.0,
            total_trades=a.total_trades or 0,
            win_rate=a.win_rate or 0.0,
            current_mode=a.current_mode or "conservative",
            rules_version=a.rules_version or 1,
            last_signal_at=a.last_signal_at.isoformat() if a.last_signal_at else None,
            last_trade_at=a.last_trade_at.isoformat() if a.last_trade_at else None,
            created_at=a.created_at.isoformat() if a.created_at else "",
            error_message=a.error_message,
        )


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    request: Request,
    session: DbSession,
    agent_type: str | None = Query(None, alias="type"),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List agents with optional filters. Non-admins only see their own agents."""
    query = select(Agent).order_by(desc(Agent.created_at))
    if agent_type:
        query = query.where(Agent.type == agent_type)
    if status_filter:
        query = query.where(Agent.status == status_filter)
    # Enforce per-user isolation unless the caller is an admin
    caller_id = getattr(request.state, "user_id", None)
    is_admin = getattr(request.state, "is_admin", False)
    if caller_id and not is_admin:
        import uuid as _uuid
        try:
            query = query.where(Agent.user_id == _uuid.UUID(caller_id))
        except (ValueError, AttributeError):
            pass
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    return [AgentResponse.from_model(a) for a in result.scalars().all()]


@router.get("/stats")
async def agent_stats(session: DbSession):
    """Aggregate agent statistics."""
    total = await session.execute(select(func.count(Agent.id)))
    running = await session.execute(
        select(func.count(Agent.id)).where(Agent.status == "RUNNING")
    )
    paused = await session.execute(
        select(func.count(Agent.id)).where(Agent.status == "PAUSED")
    )
    backtesting = await session.execute(
        select(func.count(Agent.id)).where(Agent.status == "BACKTESTING")
    )
    daily_pnl_result = await session.execute(
        select(func.coalesce(func.sum(Agent.daily_pnl), 0.0))
    )
    return {
        "total": total.scalar() or 0,
        "running": running.scalar() or 0,
        "paused": paused.scalar() or 0,
        "backtesting": backtesting.scalar() or 0,
        "daily_pnl": round(float(daily_pnl_result.scalar() or 0), 2),
    }


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AgentResponse)
async def create_agent(request: Request, payload: AgentCreate, session: DbSession):
    """Create a new agent and kick off backtesting locally."""
    import secrets
    import re
    import os

    agent_type = "trend" if payload.type == "sentiment" else payload.type

    channel_name = None
    selected_channel = (payload.config or {}).get("selected_channel")
    if isinstance(selected_channel, dict):
        channel_name = selected_channel.get("channel_name")
    analyst_name = payload.name.split(" ")[0] if payload.name else None

    if channel_name:
        channel_name = re.sub(r'[^\w\-]', '', channel_name.encode('ascii', 'ignore').decode()).strip('-')

    agent_api_key = f"phx_{secrets.token_urlsafe(32)}"
    phoenix_api_url = os.getenv("PHOENIX_API_URL", os.getenv("PUBLIC_API_URL", "http://localhost:8011"))

    agent_id = uuid.uuid4()
    caller_id = getattr(request.state, "user_id", None)
    agent_user_id: uuid.UUID | None = None
    if caller_id:
        try:
            agent_user_id = uuid.UUID(caller_id)
        except (ValueError, AttributeError):
            pass
    agent = Agent(
        id=agent_id,
        user_id=agent_user_id,
        name=payload.name,
        type=agent_type,
        status="BACKTESTING",
        channel_name=channel_name,
        analyst_name=analyst_name,
        phoenix_api_key=agent_api_key,
        config={
            "description": payload.description,
            "data_source": payload.data_source,
            "skills": payload.skills,
            "connector_ids": payload.connector_ids,
            **payload.config,
        },
    )
    session.add(agent)

    for cid in payload.connector_ids:
        link = ConnectorAgent(
            id=uuid.uuid4(),
            connector_id=uuid.UUID(cid),
            agent_id=agent_id,
            channel="*",
        )
        session.add(link)

    now = datetime.now(timezone.utc)
    backtest = AgentBacktest(
        id=uuid.uuid4(),
        agent_id=agent_id,
        status="PENDING",
        strategy_template=f"{agent_type}_default",
        start_date=now - timedelta(days=730),
        end_date=now,
        parameters={"initial_capital": 100000, "type": payload.type, "skills": payload.skills},
        metrics={},
        equity_curve=[],
        created_at=now,
    )
    session.add(backtest)
    await session.commit()
    await session.refresh(agent)

    connector_ids = payload.connector_ids
    discord_token = ""
    server_id = ""
    discord_auth_type = "bot_token"
    if connector_ids:
        conn_result = await session.execute(
            select(Connector).where(Connector.id == uuid.UUID(connector_ids[0]))
        )
        connector = conn_result.scalar_one_or_none()
        if connector:
            server_id = (connector.config or {}).get("server_id", "")
            discord_auth_type = (connector.config or {}).get("auth_type", "bot_token")
            if connector.credentials_encrypted:
                try:
                    from shared.crypto.credentials import decrypt_credentials
                    creds = decrypt_credentials(connector.credentials_encrypted)
                    discord_token = creds.get("user_token") or creds.get("bot_token", "")
                except Exception:
                    logger.warning("Could not decrypt credentials for connector %s", connector_ids[0])

    channel_id = ""
    if isinstance(selected_channel, dict):
        channel_id = selected_channel.get("channel_id", "")

    backtest_config = {
        "agent_id": str(agent_id),
        "backtest_id": str(backtest.id),
        "channel_id": channel_id,
        "channel_name": channel_name or "",
        "server_id": server_id,
        "discord_token": discord_token,
        "discord_auth_type": discord_auth_type,
        "analyst_name": payload.config.get("analyst_name", analyst_name or ""),
        "lookback_days": payload.config.get("lookback_days", 730),
        "phoenix_api_url": phoenix_api_url,
        "phoenix_api_key": agent_api_key,
        "risk_params": {
            "max_position_size_pct": payload.config.get("max_position_pct", 5.0),
            "max_daily_loss_pct": payload.config.get("max_daily_loss_pct", 3.0),
            "max_concurrent_positions": payload.config.get("max_concurrent_positions", 3),
            "confidence_threshold": 0.65,
            "stop_loss_pct": payload.config.get("stop_loss_pct", 2.0),
        },
    }

    from apps.api.src.services.agent_gateway import gateway
    await gateway.create_backtester(agent_id, backtest.id, backtest_config)

    # For analyst agents, also spawn the persona-driven analyst session immediately
    if payload.type == "analyst":
        try:
            persona_id = payload.config.get("persona_id", "aggressive_momentum")
            analyst_config = {
                **backtest_config,
                "persona_id": persona_id,
                "persona": persona_id,
                "tickers": payload.config.get("tickers", []),
                "watchlist": payload.config.get("watchlist", []),
            }
            await gateway.create_analyst_agent(agent_id, analyst_config, mode="signal_intake")
            logger.info("Spawned analyst persona agent for %s (persona=%s)", agent_id, persona_id)
        except Exception as exc:
            logger.warning("Failed to spawn analyst persona agent for %s: %s", agent_id, exc)

    return AgentResponse.from_model(agent)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, session: DbSession):
    """Get agent details."""
    result = await session.execute(
        select(Agent).where(Agent.id == uuid.UUID(agent_id))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return AgentResponse.from_model(agent)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(agent_id: str, payload: AgentUpdate, session: DbSession):
    """Update agent config or status."""
    result = await session.execute(
        select(Agent).where(Agent.id == uuid.UUID(agent_id))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if payload.name is not None:
        agent.name = payload.name
    if payload.status is not None:
        agent.status = payload.status
    if payload.config is not None:
        agent.config = {**(agent.config or {}), **payload.config}

    agent.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(agent)
    return AgentResponse.from_model(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, session: DbSession):
    """Delete an agent and stop its worker if running."""
    from apps.api.src.services.agent_gateway import gateway
    await gateway.stop_agent(uuid.UUID(agent_id))

    result = await session.execute(
        select(Agent).where(Agent.id == uuid.UUID(agent_id))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    await session.delete(agent)
    await session.commit()


@router.post("/{agent_id}/pause")
async def pause_agent(agent_id: str, session: DbSession):
    """Pause a running agent's Claude Code session."""
    from apps.api.src.services.agent_gateway import gateway
    result = await gateway.pause_agent(uuid.UUID(agent_id))
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return {"id": agent_id, "status": "PAUSED"}


@router.post("/{agent_id}/resume")
async def resume_agent(agent_id: str, session: DbSession):
    """Resume a paused agent's Claude Code session."""
    from apps.api.src.services.agent_gateway import gateway
    result = await gateway.resume_agent(uuid.UUID(agent_id))
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return {"id": agent_id, "status": "RUNNING"}


class AgentApprovePayload(BaseModel):
    trading_mode: str = "paper"
    account_id: str | None = None
    stop_loss_pct: float = 2.0
    target_profit_pct: float = 5.0
    max_daily_loss_pct: float = 5.0
    max_position_pct: float = 10.0


@router.post("/{agent_id}/approve")
async def approve_agent(agent_id: str, session: DbSession, payload: AgentApprovePayload | None = None):
    """Approve an agent after backtest review."""
    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.status != "BACKTEST_COMPLETE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent must complete backtesting before approval. Current status: {agent.status}",
        )

    if payload is None:
        payload = AgentApprovePayload()

    approval_config = {
        "trading_mode": payload.trading_mode,
        "stop_loss_pct": payload.stop_loss_pct,
        "target_profit_pct": payload.target_profit_pct,
        "max_daily_loss_pct": payload.max_daily_loss_pct,
        "max_position_pct": payload.max_position_pct,
    }
    if payload.account_id:
        approval_config["account_id"] = payload.account_id

        try:
            from shared.crypto.credentials import decrypt_credentials
            conn_result = await session.execute(
                select(Connector).where(Connector.id == uuid.UUID(payload.account_id))
            )
            connector = conn_result.scalar_one_or_none()
            if connector and connector.credentials_encrypted:
                creds = decrypt_credentials(connector.credentials_encrypted)
                if connector.type == "robinhood":
                    agent.config = {
                        **(agent.config or {}),
                        "robinhood_credentials": {
                            "username": creds.get("username", ""),
                            "password": creds.get("password", ""),
                            "totp_secret": creds.get("totp_secret", ""),
                        },
                    }
                elif connector.type in ("alpaca", "ibkr", "tradier"):
                    agent.config = {
                        **(agent.config or {}),
                        "broker_credentials": {
                            "broker": connector.type,
                            **creds,
                        },
                    }
        except Exception:
            pass

    agent.config = {**(agent.config or {}), "approval": approval_config}

    agent.status = "PAPER" if payload.trading_mode == "paper" else "APPROVED"
    agent.updated_at = datetime.now(timezone.utc)

    if not agent.manifest or not agent.manifest.get("identity"):
        channel = agent.channel_name or agent.name.lower().replace(" ", "-")
        agent.manifest = {
            "version": "1.0",
            "template": "live-trader-v1",
            "identity": {
                "name": agent.name,
                "channel": channel,
                "analyst": agent.analyst_name or "",
                "character": "balanced-intraday",
            },
            "rules": (agent.config or {}).get("rules", []),
            "modes": (agent.config or {}).get("modes", {}),
            "risk": {
                "max_daily_loss_pct": payload.max_daily_loss_pct,
                "max_position_size_pct": payload.max_position_pct,
                "stop_loss_pct": payload.stop_loss_pct,
            },
            "models": {},
            "knowledge": {},
            "credentials": {},
        }

    await session.commit()

    # Auto-spawn the live analyst session immediately after approval
    auto_spawn_result = None
    try:
        from apps.api.src.services.agent_gateway import gateway
        auto_spawn_result = await gateway.create_analyst(uuid.UUID(agent_id))
        logger.info("Auto-spawned analyst session for %s after approval: %s",
                    agent_id, auto_spawn_result)
    except Exception as exc:
        logger.warning("Failed to auto-spawn analyst for %s: %s", agent_id, exc)

    return {
        "id": agent_id,
        "status": agent.status,
        "config": agent.config,
        "session": auto_spawn_result,
    }


class SpawnPositionAgentPayload(BaseModel):
    ticker: str
    side: str  # "buy" or "sell"
    entry_price: float
    qty: int
    stop_loss: float | None = None
    take_profit: float | None = None
    reasoning: str = ""
    position_id: str | None = None


@router.post("/{agent_id}/spawn-position-agent")
async def spawn_position_agent(agent_id: str, payload: SpawnPositionAgentPayload, session: DbSession):
    """Spawn a position monitor sub-agent for a newly opened trade.

    Called by the parent analyst agent immediately after a successful order
    fills. The sub-agent runs as its own Claude Code session and monitors
    exit conditions until the position is closed.
    """
    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent agent not found")

    from apps.api.src.services.agent_gateway import gateway
    position_data = payload.model_dump()
    position_data["position_id"] = position_data.get("position_id") or str(uuid.uuid4())

    session_row_id = await gateway.create_position_agent(uuid.UUID(agent_id), position_data)
    return {
        "status": "spawned",
        "session_row_id": session_row_id,
        "position_id": position_data["position_id"],
        "ticker": payload.ticker,
    }


@router.post("/{session_id}/terminate")
async def terminate_position_agent(session_id: str, payload: dict | None = None):
    """Self-termination endpoint for position monitor sub-agents."""
    from apps.api.src.services.agent_gateway import gateway
    reason = (payload or {}).get("reason", "manual_termination")
    result = await gateway.terminate_position_agent(uuid.UUID(session_id), reason)
    return result


@router.get("/{agent_id}/position-agents")
async def list_position_agents(agent_id: str):
    """List active position monitor sub-agents for an analyst agent."""
    from apps.api.src.services.agent_gateway import gateway
    agents = await gateway.list_position_agents(uuid.UUID(agent_id))
    return {"agent_id": agent_id, "position_agents": agents, "count": len(agents)}


@router.put("/{agent_id}/pending-improvements")
async def stage_pending_improvements(agent_id: str, payload: dict, session: DbSession):
    """Supervisor agent stages improvements for user approval.

    Body: {"improvements": [{...}, {...}]}
    """
    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    new_improvements = payload.get("improvements", [])
    for item in new_improvements:
        item.setdefault("backtest_passed", None)
        item.setdefault("backtest_metrics", {})
        item.setdefault("validation_status", "pending_validation")
    existing = agent.pending_improvements or {}
    existing_items = existing.get("items", []) if isinstance(existing, dict) else []
    existing_items.extend(new_improvements)
    agent.pending_improvements = {
        "items": existing_items,
        "last_staged_at": datetime.now(timezone.utc).isoformat(),
    }
    agent.last_research_at = datetime.now(timezone.utc)
    await session.commit()
    return {"agent_id": agent_id, "staged": len(new_improvements), "total_pending": len(existing_items)}


@router.get("/{agent_id}/pending-improvements")
async def get_pending_improvements(agent_id: str, session: DbSession):
    """List pending improvements for an agent."""
    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    pending = agent.pending_improvements or {}
    return {
        "agent_id": agent_id,
        "items": pending.get("items", []) if isinstance(pending, dict) else [],
        "last_staged_at": pending.get("last_staged_at") if isinstance(pending, dict) else None,
    }


@router.post("/{agent_id}/pending-improvements/{change_id}/approve")
async def approve_improvement(agent_id: str, change_id: str, session: DbSession):
    """Apply a single staged improvement to the agent's manifest."""
    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    pending = agent.pending_improvements or {}
    items = pending.get("items", []) if isinstance(pending, dict) else []
    target = next((i for i in items if i.get("id") == change_id), None)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Improvement not found")

    # Apply the change to the manifest based on type
    manifest = dict(agent.manifest or {})
    change_type = target.get("type", "")
    proposed = target.get("proposed")

    if change_type == "raise_confidence_threshold":
        risk = manifest.setdefault("risk", {})
        risk["confidence_threshold"] = proposed
    elif change_type == "tighten_pattern_match":
        risk = manifest.setdefault("risk", {})
        risk["min_pattern_matches"] = proposed
    elif change_type == "tighten_stop_loss":
        risk = manifest.setdefault("risk", {})
        risk["stop_loss_pct"] = proposed
    # other types: just record the change as a note in manifest history

    history = manifest.setdefault("improvement_history", [])
    history.append({**target, "approved_at": datetime.now(timezone.utc).isoformat()})

    agent.manifest = manifest
    agent.rules_version = (agent.rules_version or 1) + 1

    # Remove from pending
    new_items = [i for i in items if i.get("id") != change_id]
    agent.pending_improvements = {**pending, "items": new_items}
    agent.updated_at = datetime.now(timezone.utc)

    await session.commit()
    return {"status": "approved", "change_id": change_id, "agent_id": agent_id,
            "new_rules_version": agent.rules_version}


@router.post("/{agent_id}/pending-improvements/{change_id}/reject")
async def reject_improvement(agent_id: str, change_id: str, session: DbSession):
    """Reject and discard a staged improvement."""
    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    pending = agent.pending_improvements or {}
    items = pending.get("items", []) if isinstance(pending, dict) else []
    new_items = [i for i in items if i.get("id") != change_id]
    if len(new_items) == len(items):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Improvement not found")

    agent.pending_improvements = {**pending, "items": new_items}
    await session.commit()
    return {"status": "rejected", "change_id": change_id, "agent_id": agent_id}


class ImprovementValidatePayload(BaseModel):
    backtest_metrics: dict[str, Any]


@router.post("/{agent_id}/improvements/{improvement_id}/validate")
async def validate_improvement(
    agent_id: str,
    improvement_id: str,
    payload: ImprovementValidatePayload,
    session: DbSession,
) -> dict:
    """Validate a pending improvement using backtest metrics.

    Thresholds: Sharpe >= 0.8, Win Rate >= 0.53, Max Drawdown >= -0.15,
    Profit Factor >= 1.3, Min Trades >= 15.
    BORDERLINE = misses exactly ONE threshold by <10%.
    Sets validation_status: approved | borderline | rejected.
    """
    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    pending = agent.pending_improvements or {}
    items: list[dict] = pending.get("items", []) if isinstance(pending, dict) else []
    target = next((i for i in items if i.get("id") == improvement_id), None)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Improvement not found")

    metrics = payload.backtest_metrics
    thresholds = {
        "sharpe": (metrics.get("sharpe", 0.0), 0.8, True),
        "win_rate": (metrics.get("win_rate", 0.0), 0.53, True),
        "max_drawdown": (metrics.get("max_drawdown", -999.0), -0.15, True),  # must be >= -0.15
        "profit_factor": (metrics.get("profit_factor", 0.0), 1.3, True),
        "trade_count": (metrics.get("trade_count", 0), 15, True),
    }

    missed = []
    borderline_misses = []
    for name, (value, threshold, gte) in thresholds.items():
        passes = value >= threshold if gte else value <= threshold
        if not passes:
            missed.append(name)
            if threshold != 0:
                pct_miss = abs(value - threshold) / abs(threshold)
            else:
                pct_miss = abs(value - threshold)
            if pct_miss < 0.10:
                borderline_misses.append(name)

    if not missed:
        validation_status = "approved"
    elif len(missed) == 1 and len(borderline_misses) == 1:
        validation_status = "borderline"
    else:
        validation_status = "rejected"

    target["backtest_passed"] = validation_status == "approved"
    target["backtest_metrics"] = metrics
    target["validation_status"] = validation_status

    agent.pending_improvements = {**pending, "items": items}
    await session.commit()

    return {
        "improvement_id": improvement_id,
        "validation_status": validation_status,
        "backtest_passed": target["backtest_passed"],
        "backtest_metrics": metrics,
        "thresholds_missed": missed,
    }


@router.get("/{agent_id}/runtime-info")
async def get_runtime_info(agent_id: str, session: DbSession):
    """Phase 5.1: Runtime visibility for an agent's Claude Code session.

    Returns host, PID, working directory, session_id, memory usage, uptime.
    """
    import os as _os
    import socket as _socket
    from shared.db.models.agent_session import AgentSession

    sess_result = await session.execute(
        select(AgentSession)
        .where(AgentSession.agent_id == uuid.UUID(agent_id),
               AgentSession.status.in_(["running", "starting"]))
        .order_by(desc(AgentSession.started_at))
        .limit(1)
    )
    sess = sess_result.scalar_one_or_none()
    if not sess:
        return {"agent_id": agent_id, "running": False}

    info = {
        "agent_id": agent_id,
        "running": True,
        "session_row_id": str(sess.id),
        "session_id": sess.session_id,
        "agent_type": sess.agent_type,
        "session_role": sess.session_role,
        "working_directory": sess.working_dir,
        "started_at": sess.started_at.isoformat() if sess.started_at else None,
        "host_name": sess.host_name or _socket.gethostname(),
        "pid": sess.pid or _os.getpid(),
    }

    if sess.started_at:
        uptime = (datetime.now(timezone.utc) - sess.started_at).total_seconds()
        info["uptime_seconds"] = int(uptime)

    # Memory usage (best-effort)
    try:
        import psutil  # type: ignore
        proc = psutil.Process(info["pid"])
        info["memory_usage_mb"] = round(proc.memory_info().rss / 1024 / 1024, 1)
    except Exception:
        info["memory_usage_mb"] = None

    return info


@router.post("/{agent_id}/instruct")
async def instruct_agent(agent_id: str, payload: dict, session: DbSession):
    """Send an instruction to a running agent via gateway.send_task()."""
    instruction = (payload or {}).get("instruction", "")
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction required")

    from apps.api.src.services.agent_gateway import gateway
    result = await gateway.send_task(uuid.UUID(agent_id), instruction)
    return {"agent_id": agent_id, "result": result}


@router.get("/{agent_id}/activity-feed")
async def activity_feed(agent_id: str, session: DbSession, limit: int = 100):
    """Unified activity feed: logs + trades + messages sorted by time."""
    from shared.db.models.agent import AgentLog
    from shared.db.models.agent_trade import AgentTrade
    from shared.db.models.agent_message import AgentMessage
    from shared.db.models.system_log import SystemLog

    aid = uuid.UUID(agent_id)
    feed: list[dict] = []

    # Agent logs
    try:
        logs_result = await session.execute(
            select(AgentLog)
            .where(AgentLog.agent_id == aid)
            .order_by(desc(AgentLog.created_at))
            .limit(limit)
        )
        for log in logs_result.scalars().all():
            feed.append({
                "type": "log",
                "id": str(log.id),
                "level": log.level,
                "message": log.message,
                "timestamp": log.created_at.isoformat() if log.created_at else None,
            })
    except Exception:
        pass

    # System logs
    try:
        sys_result = await session.execute(
            select(SystemLog)
            .where(SystemLog.agent_id == agent_id)
            .order_by(desc(SystemLog.created_at))
            .limit(limit)
        )
        for log in sys_result.scalars().all():
            feed.append({
                "type": "system_log",
                "id": str(log.id),
                "level": log.level,
                "message": log.message,
                "step": log.step,
                "timestamp": log.created_at.isoformat() if log.created_at else None,
            })
    except Exception:
        pass

    # Trades
    try:
        trades_result = await session.execute(
            select(AgentTrade)
            .where(AgentTrade.agent_id == aid)
            .order_by(desc(AgentTrade.created_at))
            .limit(limit)
        )
        for trade in trades_result.scalars().all():
            feed.append({
                "type": "trade",
                "id": str(trade.id),
                "ticker": trade.ticker,
                "side": trade.side,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "pnl_dollar": trade.pnl_dollar,
                "status": trade.status,
                "decision_status": trade.decision_status,
                "timestamp": trade.created_at.isoformat() if trade.created_at else None,
            })
    except Exception:
        pass

    # Messages (knowledge sharing)
    try:
        msgs_result = await session.execute(
            select(AgentMessage)
            .where(
                (AgentMessage.from_agent_id == aid) | (AgentMessage.to_agent_id == aid)
            )
            .order_by(desc(AgentMessage.created_at))
            .limit(limit)
        )
        for msg in msgs_result.scalars().all():
            feed.append({
                "type": "message",
                "id": str(msg.id),
                "intent": msg.intent,
                "from_agent": str(msg.from_agent_id),
                "to_agent": str(msg.to_agent_id) if msg.to_agent_id else "broadcast",
                "body": msg.body,
                "timestamp": msg.created_at.isoformat() if msg.created_at else None,
            })
    except Exception:
        pass

    feed.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return feed[:limit]


@router.get("/graph")
async def get_agent_graph(session: DbSession):
    """Phase 3.1: Agent topology graph data for dashboard visualization."""
    from shared.db.models.agent_message import AgentMessage

    agents_result = await session.execute(select(Agent))
    all_agents = list(agents_result.scalars().all())

    nodes = []
    for agent in all_agents:
        manifest = agent.manifest or {}
        nodes.append({
            "id": str(agent.id),
            "name": agent.name,
            "status": agent.status,
            "type": agent.type,
            "character": manifest.get("identity", {}).get("character", "unknown"),
            "tools": manifest.get("tools", []),
            "channels": [agent.channel_name] if agent.channel_name else [],
            "win_rate": agent.win_rate,
            "total_trades": agent.total_trades,
        })

    # Recent edges from agent_messages (last 24h)
    edges_dict: dict[tuple, dict] = {}
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        msgs_result = await session.execute(
            select(AgentMessage)
            .where(AgentMessage.created_at >= cutoff)
            .order_by(desc(AgentMessage.created_at))
            .limit(500)
        )
        for msg in msgs_result.scalars().all():
            if not msg.to_agent_id:
                continue
            key = (str(msg.from_agent_id), str(msg.to_agent_id))
            if key not in edges_dict:
                edges_dict[key] = {
                    "from": key[0],
                    "to": key[1],
                    "type": "knowledge_share",
                    "intent": msg.intent,
                    "count": 0,
                    "last_message_at": msg.created_at.isoformat() if msg.created_at else None,
                }
            edges_dict[key]["count"] += 1
    except Exception as exc:
        logger.debug("[graph] agent_messages edges skipped: %s", exc)

    # P8: Synthetic edges when agents share a connector (Discord channel → agent)
    try:
        from shared.db.models.connector import ConnectorAgent
        ca_res = await session.execute(select(ConnectorAgent))
        by_connector: dict[str, list[str]] = {}
        for ca in ca_res.scalars().all():
            by_connector.setdefault(str(ca.connector_id), []).append(str(ca.agent_id))
        for conn_id, agent_ids in by_connector.items():
            if len(agent_ids) < 2:
                continue
            for i, a_id in enumerate(agent_ids):
                for b_id in agent_ids[i + 1:]:
                    key = (a_id, b_id)
                    rev = (b_id, a_id)
                    if key not in edges_dict and rev not in edges_dict:
                        edges_dict[key] = {
                            "from": a_id, "to": b_id,
                            "type": "shared_connector",
                            "intent": "same_channel",
                            "count": 1,
                            "connector_id": conn_id,
                        }
    except Exception as exc:
        logger.debug("[graph] shared-connector edges skipped: %s", exc)

    # Note: parent→child edges removed — Agent model has no parent_agent_id column

    return {"nodes": nodes, "edges": list(edges_dict.values())}


@router.post("/supervisor/run")
async def trigger_supervisor():
    """Manually trigger the supervisor agent (also called by Claude Code cron at 4:30 PM ET)."""
    try:
        from apps.api.src.services.agent_gateway import gateway
        session_id = await gateway.create_supervisor_agent()
        return {"status": "started", "session_row_id": session_id}
    except Exception as exc:
        logger.exception("Supervisor trigger failed")
        return {"status": "error", "error": str(exc)[:500]}


@router.get("/{agent_id}/paper-portfolio")
async def get_paper_portfolio(agent_id: str, session: DbSession):
    """Get paper trading portfolio for an agent.

    Returns simulated positions, P&L, and metrics from the watchlist table.
    """
    from shared.db.models.watchlist import Watchlist
    result = await session.execute(
        select(Watchlist)
        .where(Watchlist.agent_id == uuid.UUID(agent_id))
        .order_by(desc(Watchlist.added_at))
    )
    rows = result.scalars().all()

    open_positions = [w for w in rows if w.status == "open"]
    closed_positions = [w for w in rows if w.status == "closed"]

    total_unrealized = sum(w.simulated_pnl for w in open_positions)
    total_realized = sum(w.simulated_pnl for w in closed_positions)
    wins = sum(1 for w in closed_positions if w.simulated_pnl > 0)

    return {
        "agent_id": agent_id,
        "open_positions": len(open_positions),
        "closed_positions": len(closed_positions),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "total_realized_pnl": round(total_realized, 2),
        "win_rate": round(wins / len(closed_positions), 3) if closed_positions else 0.0,
        "positions": [
            {
                "id": str(w.id),
                "ticker": w.ticker,
                "side": w.side,
                "quantity": w.quantity,
                "entry_price": w.entry_price_at_add,
                "current_price": w.current_price,
                "simulated_pnl": w.simulated_pnl,
                "simulated_pnl_pct": w.simulated_pnl_pct,
                "status": w.status,
                "added_at": w.added_at.isoformat() if w.added_at else None,
                "closed_at": w.closed_at.isoformat() if w.closed_at else None,
                "signal_data": w.signal_data,
            }
            for w in rows
        ],
    }


@router.post("/{agent_id}/promote")
async def promote_agent(agent_id: str, session: DbSession):
    """Promote an approved agent to live trading via Claude Code agent."""
    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.status not in ("APPROVED", "PAPER", "BACKTEST_COMPLETE"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Only APPROVED/PAPER agents can be promoted, current: {agent.status}")

    from apps.api.src.services.agent_gateway import gateway
    mgr_result = await gateway.create_analyst(uuid.UUID(agent_id))
    return {"id": agent_id, "status": "RUNNING", "worker": mgr_result}


class LiveMessagePayload(BaseModel):
    content: str
    author: str = ""
    channel: str = ""


@router.post("/{agent_id}/process-message")
async def process_live_message(agent_id: str, payload: LiveMessagePayload, session: DbSession):
    """Process a live message through the agent's intelligence pipeline."""
    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.status != "RUNNING":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Agent is not running, current: {agent.status}")

    bt_result = await session.execute(
        select(AgentBacktest)
        .where(AgentBacktest.agent_id == agent.id)
        .order_by(desc(AgentBacktest.created_at))
        .limit(1)
    )
    bt = bt_result.scalar_one_or_none()
    rules = (bt.metrics or {}).get("rules", []) if bt else []

    from services.execution.src.live_pipeline import LiveTradingPipeline
    pipeline = LiveTradingPipeline(
        agent_id=agent_id,
        agent_config=agent.config or {},
        intelligence_rules=rules,
    )

    trade_result = await pipeline.process_message(
        content=payload.content,
        author=payload.author,
        channel=payload.channel,
    )

    return {"result": trade_result, "pipeline_stats": pipeline.get_stats()}


@router.get("/{agent_id}/backtest")
async def get_agent_backtest(agent_id: str, session: DbSession):
    """Get the latest backtest for an agent."""
    result = await session.execute(
        select(AgentBacktest)
        .where(AgentBacktest.agent_id == uuid.UUID(agent_id))
        .order_by(desc(AgentBacktest.created_at))
        .limit(1)
    )
    bt = result.scalar_one_or_none()
    if not bt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No backtest found for this agent")
    return {
        "id": str(bt.id),
        "agent_id": str(bt.agent_id),
        "status": bt.status,
        "current_step": bt.current_step,
        "progress_pct": bt.progress_pct or 0,
        "strategy_template": bt.strategy_template,
        "start_date": bt.start_date.isoformat() if bt.start_date else None,
        "end_date": bt.end_date.isoformat() if bt.end_date else None,
        "parameters": bt.parameters,
        "metrics": bt.metrics,
        "equity_curve": bt.equity_curve,
        "total_trades": bt.total_trades,
        "win_rate": bt.win_rate,
        "sharpe_ratio": bt.sharpe_ratio,
        "max_drawdown": bt.max_drawdown,
        "total_return": bt.total_return,
        "error_message": bt.error_message,
        "completed_at": bt.completed_at.isoformat() if bt.completed_at else None,
        "created_at": bt.created_at.isoformat() if bt.created_at else None,
    }


@router.post("/{agent_id}/kill-backtest")
async def kill_backtest(agent_id: str, session: DbSession):
    """F4: Cancel a stuck backtest task and mark its row as FAILED.

    Finds any asyncio task for this agent in the agent_gateway's _running_tasks
    map, cancels it, and updates the latest RUNNING backtest row to FAILED.
    """
    from apps.api.src.services.agent_gateway import _running_tasks
    from shared.db.models.agent import AgentBacktest

    agent_uuid = uuid.UUID(agent_id)
    cancelled_keys: list[str] = []

    for key in list(_running_tasks.keys()):
        if key.startswith(agent_id) or str(agent_uuid) in key:
            task = _running_tasks.get(key)
            if task and not task.done():
                task.cancel()
                cancelled_keys.append(key)

    # Mark any running backtest row for this agent as FAILED
    bt_result = await session.execute(
        select(AgentBacktest)
        .where(AgentBacktest.agent_id == agent_uuid,
               AgentBacktest.status.in_(["RUNNING", "PENDING"]))
    )
    killed_rows = 0
    for bt in bt_result.scalars().all():
        bt.status = "FAILED"
        bt.error_message = "killed_by_user via /kill-backtest"
        killed_rows += 1

    # Reset agent status if it was stuck in BACKTESTING
    agent_result = await session.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = agent_result.scalar_one_or_none()
    if agent and agent.status == "BACKTESTING":
        agent.status = "CREATED"

    await session.commit()

    return {
        "killed": True,
        "cancelled_tasks": cancelled_keys,
        "failed_backtests": killed_rows,
    }


@router.post("/{agent_id}/backtest-complete")
async def complete_agent_backtest(agent_id: str, session: DbSession):
    """Run the backtest pipeline for an agent."""
    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.status != "BACKTESTING":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Agent is not backtesting, current: {agent.status}")

    bt_result = await session.execute(
        select(AgentBacktest)
        .where(AgentBacktest.agent_id == agent.id, AgentBacktest.status.in_(["PENDING", "RUNNING"]))
        .order_by(desc(AgentBacktest.created_at))
        .limit(1)
    )
    bt = bt_result.scalar_one_or_none()
    if not bt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active backtest found")

    try:
        from services.backtest_runner.src.pipeline import run_backtest_pipeline
        result = await run_backtest_pipeline(session=session, agent_id=agent.id, backtest_id=bt.id)
        if "error" not in result and result.get("total_trades", 0) > 0:
            await session.refresh(bt)
            await session.refresh(agent)
            return {"backtest_id": str(bt.id), "agent_id": agent_id, "status": bt.status, "pipeline": "real", **result}
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = f"Pipeline error: {str(e)[:500]}"
        now = datetime.now(timezone.utc)
        bt.status = "FAILED"
        bt.error_message = error_msg
        bt.completed_at = now
        agent.status = "CREATED"
        agent.updated_at = now
        await session.commit()
        return {"backtest_id": str(bt.id), "agent_id": agent_id, "status": "FAILED", "error": error_msg}

    now = datetime.now(timezone.utc)
    error_msg = result.get("error", "Pipeline returned no trades")
    bt.status = "FAILED"
    bt.error_message = error_msg
    bt.completed_at = now
    agent.status = "CREATED"
    agent.updated_at = now
    await session.commit()
    return {"backtest_id": str(bt.id), "agent_id": agent_id, "status": "FAILED", "error": error_msg}


@router.get("/{agent_id}/backtest-trades")
async def get_backtest_trades(agent_id: str, session: DbSession, limit: int = Query(200, ge=1, le=1000)):
    """Get reconstructed trades from the latest backtest."""
    from shared.db.models.backtest_trade import BacktestTrade

    bt_result = await session.execute(
        select(AgentBacktest).where(AgentBacktest.agent_id == uuid.UUID(agent_id)).order_by(desc(AgentBacktest.created_at)).limit(1)
    )
    bt = bt_result.scalar_one_or_none()
    if not bt:
        return {"trades": [], "backtest_id": None}

    trades_result = await session.execute(
        select(BacktestTrade).where(BacktestTrade.backtest_id == bt.id).order_by(BacktestTrade.entry_time.asc()).limit(limit)
    )
    trades = trades_result.scalars().all()
    return {
        "backtest_id": str(bt.id),
        "trades": [
            {
                "id": str(t.id), "ticker": t.ticker, "side": t.side,
                "entry_price": t.entry_price, "exit_price": t.exit_price,
                "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                "pnl": t.pnl, "pnl_pct": t.pnl_pct,
                "holding_period_hours": t.holding_period_hours, "is_profitable": t.is_profitable,
                "entry_rsi": t.entry_rsi, "entry_macd": t.entry_macd,
                "entry_bollinger_position": t.entry_bollinger_position,
                "entry_volume_ratio": t.entry_volume_ratio,
                "market_vix": t.market_vix, "market_spy_change": t.market_spy_change,
                "hour_of_day": t.hour_of_day, "day_of_week": t.day_of_week,
                "is_pre_market": t.is_pre_market, "pattern_tags": t.pattern_tags,
                "option_flow_sentiment": t.option_flow_sentiment,
            }
            for t in trades
        ],
    }


@router.get("/{agent_id}/logs")
async def get_agent_logs(agent_id: str, session: DbSession, level: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """Stream agent logs from DB."""
    from shared.db.models.agent import AgentLog
    query = select(AgentLog).where(AgentLog.agent_id == uuid.UUID(agent_id)).order_by(desc(AgentLog.created_at))
    if level:
        query = query.where(AgentLog.level == level.upper())
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    logs = result.scalars().all()
    return [
        {"id": str(log.id), "level": log.level, "message": log.message, "context": log.context, "created_at": log.created_at.isoformat() if log.created_at else ""}
        for log in logs
    ]


# -- Live Agent Endpoints ---------------------------------------------------


class LiveTradeCreate(BaseModel):
    ticker: str
    side: str
    option_type: str | None = None
    strike: float | None = None
    expiry: str | None = None
    entry_price: float
    quantity: int = 1
    model_confidence: float | None = None
    pattern_matches: int | None = None
    reasoning: str | None = None
    signal_raw: str | None = None
    broker_order_id: str | None = None
    decision_status: str | None = "accepted"
    rejection_reason: str | None = None
    status: str | None = "open"
    decision_trail: dict | None = None


@router.get("/{agent_id}/live-trades")
async def get_live_trades(agent_id: str, session: DbSession, status_filter: str | None = Query(None, alias="status"), limit: int = Query(100, ge=1, le=1000)):
    """Live trade history from a running agent."""
    from shared.db.models.agent_trade import AgentTrade
    query = select(AgentTrade).where(AgentTrade.agent_id == uuid.UUID(agent_id)).order_by(desc(AgentTrade.entry_time)).limit(limit)
    if status_filter:
        query = query.where(AgentTrade.status == status_filter)
    result = await session.execute(query)
    trades = result.scalars().all()
    return [
        {
            "id": str(t.id), "ticker": t.ticker, "side": t.side, "option_type": t.option_type,
            "strike": t.strike, "entry_price": t.entry_price, "exit_price": t.exit_price,
            "quantity": t.quantity,
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "pnl_dollar": t.pnl_dollar, "pnl_pct": t.pnl_pct, "status": t.status,
            "model_confidence": t.model_confidence, "pattern_matches": t.pattern_matches,
            "reasoning": t.reasoning, "signal_raw": t.signal_raw,
            "broker_order_id": t.broker_order_id,
            "decision_status": t.decision_status, "rejection_reason": t.rejection_reason,
            "decision_trail": t.decision_trail if hasattr(t, "decision_trail") else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in trades
    ]


@router.post("/{agent_id}/live-trades", status_code=status.HTTP_201_CREATED)
async def report_live_trade(agent_id: str, payload: LiveTradeCreate, session: DbSession):
    """Agent reports a new trade (callback from trading worker or Claude Code)."""
    from shared.db.models.agent_trade import AgentTrade
    from datetime import date as date_type

    trade_status = payload.status or "open"
    trade = AgentTrade(
        id=uuid.uuid4(), agent_id=uuid.UUID(agent_id),
        ticker=payload.ticker, side=payload.side, option_type=payload.option_type,
        strike=payload.strike,
        expiry=date_type.fromisoformat(payload.expiry) if payload.expiry else None,
        entry_price=payload.entry_price, quantity=payload.quantity,
        entry_time=datetime.now(timezone.utc), status=trade_status,
        model_confidence=payload.model_confidence, pattern_matches=payload.pattern_matches,
        reasoning=payload.reasoning, signal_raw=payload.signal_raw, broker_order_id=payload.broker_order_id,
        decision_status=payload.decision_status or "accepted",
        rejection_reason=payload.rejection_reason,
    )
    if hasattr(trade, "decision_trail") and payload.decision_trail:
        trade.decision_trail = payload.decision_trail
    session.add(trade)

    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if agent:
        agent.total_trades = (agent.total_trades or 0) + 1
        agent.last_trade_at = datetime.now(timezone.utc)

    await session.commit()
    return {"id": str(trade.id), "status": "recorded"}


@router.get("/{agent_id}/positions")
async def get_agent_positions(agent_id: str, session: DbSession):
    """Get open positions for an agent."""
    from shared.db.models.agent_trade import AgentTrade
    result = await session.execute(
        select(AgentTrade).where(AgentTrade.agent_id == uuid.UUID(agent_id), AgentTrade.status == "open")
    )
    trades = result.scalars().all()
    return [
        {"id": str(t.id), "ticker": t.ticker, "side": t.side, "entry_price": t.entry_price, "quantity": t.quantity, "entry_time": t.entry_time.isoformat() if t.entry_time else None, "model_confidence": t.model_confidence}
        for t in trades
    ]


@router.get("/{agent_id}/metrics")
async def get_agent_metrics(agent_id: str, session: DbSession):
    """Latest metrics snapshot."""
    from shared.db.models.agent_metric import AgentMetric
    result = await session.execute(
        select(AgentMetric).where(AgentMetric.agent_id == uuid.UUID(agent_id)).order_by(desc(AgentMetric.timestamp)).limit(1)
    )
    metric = result.scalar_one_or_none()
    if not metric:
        return {"agent_id": agent_id, "metrics": None}
    return {
        "agent_id": agent_id, "timestamp": metric.timestamp.isoformat(),
        "portfolio_value": metric.portfolio_value, "daily_pnl": metric.daily_pnl,
        "open_positions": metric.open_positions, "trades_today": metric.trades_today,
        "win_rate": metric.win_rate, "avg_confidence": metric.avg_confidence,
        "signals_processed": metric.signals_processed, "tokens_used": metric.tokens_used,
        "status": metric.status,
    }


@router.post("/{agent_id}/metrics")
async def report_agent_metrics(agent_id: str, session: DbSession, payload: dict[str, Any] | None = None):
    """Agent reports metrics (callback from trading worker or Claude Code)."""
    from shared.db.models.agent_metric import AgentMetric
    if payload is None:
        payload = {}
    metric = AgentMetric(
        id=uuid.uuid4(), agent_id=uuid.UUID(agent_id),
        portfolio_value=payload.get("portfolio_value"), daily_pnl=payload.get("daily_pnl"),
        open_positions=payload.get("open_positions"), trades_today=payload.get("trades_today"),
        win_rate=payload.get("win_rate"), avg_confidence=payload.get("avg_confidence"),
        signals_processed=payload.get("signals_processed"), tokens_used=payload.get("tokens_used"),
        status=payload.get("status"),
    )
    session.add(metric)
    await session.commit()
    return {"recorded": True}


@router.get("/{agent_id}/metrics/history")
async def get_agent_metrics_history(agent_id: str, session: DbSession, limit: int = Query(100, ge=1, le=1000)):
    """Metrics over time for charts."""
    from shared.db.models.agent_metric import AgentMetric
    result = await session.execute(
        select(AgentMetric).where(AgentMetric.agent_id == uuid.UUID(agent_id)).order_by(desc(AgentMetric.timestamp)).limit(limit)
    )
    metrics = result.scalars().all()
    return [
        {"timestamp": m.timestamp.isoformat(), "portfolio_value": m.portfolio_value, "daily_pnl": m.daily_pnl, "open_positions": m.open_positions, "trades_today": m.trades_today, "win_rate": m.win_rate}
        for m in reversed(metrics)
    ]


@router.get("/{agent_id}/chat")
async def get_agent_chat(agent_id: str, session: DbSession, limit: int = Query(50, ge=1, le=200)):
    """Get chat history with an agent."""
    from shared.db.models.agent_chat import AgentChatMessage
    result = await session.execute(
        select(AgentChatMessage).where(AgentChatMessage.agent_id == uuid.UUID(agent_id)).order_by(AgentChatMessage.created_at.asc()).limit(limit)
    )
    messages = result.scalars().all()
    return [
        {"id": str(m.id), "role": m.role, "content": m.content, "message_type": getattr(m, "message_type", "text") or "text", "metadata": getattr(m, "extra_data", {}) or {}, "created_at": m.created_at.isoformat()}
        for m in messages
    ]


@router.post("/{agent_id}/chat")
async def send_agent_chat(agent_id: str, payload: dict[str, Any], session: DbSession):
    """Send a message to the agent. In V3, agent communication goes through the DB."""
    from shared.db.models.agent_chat import AgentChatMessage

    content = payload.get("message", payload.get("content", ""))
    if not content:
        raise HTTPException(status_code=400, detail="message is required")

    msg_type = payload.get("message_type", "text")
    msg_metadata = payload.get("metadata", {})

    user_msg = AgentChatMessage(
        id=uuid.uuid4(), agent_id=uuid.UUID(agent_id),
        role="user", content=content, message_type=msg_type, extra_data=msg_metadata,
    )
    session.add(user_msg)

    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    await session.commit()

    # Route through Chat Gateway — SDK session with full MCP tool access.
    # Reply lands in agent_chat_messages with role='agent' within seconds.
    try:
        from apps.api.src.services.agent_gateway import gateway  # noqa: PLC0415
        asyncio.ensure_future(gateway.chat_with_agent(uuid.UUID(agent_id), content))
    except Exception as exc:
        logger.warning("[chat] chat_with_agent dispatch failed: %s", exc)

    return {"user_message": content, "message_type": msg_type, "status": "queued"}


@router.post("/{agent_id}/command")
async def send_agent_command(agent_id: str, session: DbSession, payload: dict[str, Any] | None = None):
    """Send operational command to agent (pause/resume/switch_mode/update_config)."""
    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    body = payload or {}
    action = body.get("action", body.get("command", "status"))

    if action == "pause":
        from apps.api.src.services.agent_gateway import gateway
        await gateway.pause_agent(uuid.UUID(agent_id))
        return {"action": "pause", "result": "Agent paused"}

    if action == "resume":
        from apps.api.src.services.agent_gateway import gateway
        await gateway.resume_agent(uuid.UUID(agent_id))
        return {"action": "resume", "result": "Agent resumed"}

    if action == "switch_mode":
        new_mode = body.get("mode", "conservative")
        if new_mode not in ("aggressive", "conservative"):
            raise HTTPException(status_code=400, detail="mode must be aggressive or conservative")
        agent.current_mode = new_mode
        if agent.manifest:
            agent.manifest = {**agent.manifest, "_active_mode": new_mode}
        agent.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return {"action": "switch_mode", "result": f"Mode changed to {new_mode}"}

    if action == "update_config":
        config_patch = body.get("config", {})
        if not config_patch:
            raise HTTPException(status_code=400, detail="config is required for update_config action")

        if "rules" in config_patch and agent.manifest:
            manifest = dict(agent.manifest)
            manifest["rules"] = config_patch.pop("rules")
            agent.manifest = manifest
            agent.rules_version = (agent.rules_version or 1) + 1

        if "modes" in config_patch and agent.manifest:
            manifest = dict(agent.manifest)
            manifest["modes"] = config_patch.pop("modes")
            agent.manifest = manifest

        if "risk" in config_patch and agent.manifest:
            manifest = dict(agent.manifest)
            manifest["risk"] = config_patch.pop("risk")
            agent.manifest = manifest

        if config_patch:
            agent.config = {**(agent.config or {}), **config_patch}

        agent.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return {"action": "update_config", "result": "Config updated", "rules_version": agent.rules_version}

    return {"action": action, "result": "Unknown action"}


# -- Manifest CRUD ----------------------------------------------------------


@router.get("/{agent_id}/manifest")
async def get_agent_manifest(agent_id: str, session: DbSession):
    """Return the agent's current manifest."""
    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    manifest = agent.manifest or {}
    if not manifest and agent.config:
        manifest = {
            "version": "1.0", "template": "live-trader-v1",
            "identity": {"name": agent.name, "channel": agent.channel_name or "", "analyst": agent.analyst_name or "", "character": "balanced-intraday"},
            "rules": (agent.config or {}).get("rules", []),
            "modes": (agent.config or {}).get("modes", {}),
            "risk": (agent.config or {}).get("risk_params", (agent.config or {}).get("risk", {})),
            "models": {"primary": agent.model_type or "unknown", "accuracy": agent.model_accuracy or 0},
            "tools": [], "skills": [], "knowledge": {},
        }

    return {"agent_id": agent_id, "manifest": manifest, "current_mode": agent.current_mode, "rules_version": agent.rules_version}


@router.put("/{agent_id}/manifest")
async def update_agent_manifest(agent_id: str, payload: dict[str, Any], session: DbSession):
    """Update the agent's manifest."""
    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    current = dict(agent.manifest or {})
    rules_changed = "rules" in payload and payload["rules"] != current.get("rules")

    for key in ("rules", "modes", "risk", "knowledge", "models", "identity", "tools", "skills"):
        if key in payload:
            current[key] = payload[key]

    agent.manifest = current
    if rules_changed:
        agent.rules_version = (agent.rules_version or 1) + 1
    agent.updated_at = datetime.now(timezone.utc)
    await session.commit()

    return {"agent_id": agent_id, "manifest": agent.manifest, "rules_version": agent.rules_version}


# -- Backtest Progress Callback (used by Claude Code agents) --


class BacktestProgressPayload(BaseModel):
    step: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1)
    progress_pct: int | None = Field(default=None, ge=0, le=100)
    level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARN|ERROR)$")
    metrics: dict[str, Any] | None = None
    status: str | None = None


@router.post("/{agent_id}/backtest-progress", status_code=201)
async def report_backtest_progress(agent_id: str, payload: BacktestProgressPayload, session: DbSession):
    """Callback endpoint for backtesting progress from Claude Code agents."""
    from shared.db.models.system_log import SystemLog

    bt_result = await session.execute(
        select(AgentBacktest).where(AgentBacktest.agent_id == uuid.UUID(agent_id), AgentBacktest.status == "RUNNING").order_by(desc(AgentBacktest.created_at)).limit(1)
    )
    bt = bt_result.scalar_one_or_none()
    backtest_id = str(bt.id) if bt else None

    log = SystemLog(
        id=uuid.uuid4(), source="backtest", level=payload.level, service="backtesting-agent",
        agent_id=agent_id, backtest_id=backtest_id,
        message=payload.message, step=payload.step, progress_pct=payload.progress_pct, details=payload.metrics or {},
    )
    session.add(log)

    if bt:
        if payload.progress_pct is not None:
            bt.progress_pct = payload.progress_pct
        bt.current_step = payload.step
        if payload.metrics:
            bt.metrics = {**(bt.metrics or {}), **payload.metrics}

    if payload.status == "COMPLETED" and bt:
        bt.status = "COMPLETED"
        bt.completed_at = datetime.now(timezone.utc)

        m = bt.metrics or {}
        bt.total_trades = m.get("total_trades") or m.get("trades") or 0
        bt.win_rate = m.get("win_rate")
        bt.sharpe_ratio = m.get("sharpe_ratio")
        bt.max_drawdown = m.get("max_drawdown")
        bt.total_return = m.get("total_return")

        agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
        agent = agent_result.scalar_one_or_none()
        if agent:
            agent.status = "BACKTEST_COMPLETE"
            agent.updated_at = datetime.now(timezone.utc)
            agent.model_type = m.get("best_model") or m.get("model")
            agent.model_accuracy = m.get("accuracy")
            agent.total_trades = bt.total_trades
            agent.win_rate = bt.win_rate or 0.0

        if m.get("auto_create_analyst"):
            try:
                from apps.api.src.services.agent_gateway import gateway, DATA_DIR
                # Look up the latest backtest version dir from latest.json
                from pathlib import Path
                latest_pointer = DATA_DIR / f"backtest_{agent_id}" / "latest.json"
                bt_dir = None
                if latest_pointer.exists():
                    try:
                        latest = json.loads(latest_pointer.read_text())
                        bt_dir = Path(latest.get("output_dir", ""))
                    except Exception:
                        pass
                if bt_dir is None:
                    bt_dir = DATA_DIR / f"backtest_{agent_id}" / "output"
                await gateway._auto_create_analyst(uuid.UUID(agent_id), {}, bt_dir)
            except Exception as exc:
                logger.warning("Auto-create analyst failed for %s: %s", agent_id, exc)

    # Phase 3.1: Notification dispatch for trade events
    try:
        m = payload.metrics or {}
        if payload.step in ("trade_entry", "trade_exit", "agent_wake", "morning_briefing_complete",
                            "watchlist_add", "paper_trade_add", "paper_trade_close", "risk_alert"):
            from apps.api.src.services.notification_dispatcher import notification_dispatcher
            event_type = payload.step
            # Map a few common variants
            if payload.step == "paper_trade_add":
                event_type = "paper_trade"
            elif payload.step == "paper_trade_close":
                event_type = "trade_exit"

            # Build context for the template
            agent_result_n = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
            agent_n = agent_result_n.scalar_one_or_none()
            ctx = dict(m) if m else {}
            ctx.setdefault("agent_name", agent_n.name if agent_n else "Agent")
            ctx.setdefault("channel_name", agent_n.channel_name if agent_n else "")

            await notification_dispatcher.dispatch(
                event_type=event_type,
                agent_id=agent_id,
                title=None,  # Use template
                body=payload.message,
                data=ctx,
                channels=["db", "ws", "whatsapp"],
            )
    except Exception as exc:
        logger.warning("Notification dispatch failed for %s/%s: %s",
                       agent_id, payload.step, exc)

    if payload.status == "FAILED" and bt:
        bt.status = "FAILED"
        bt.error_message = payload.message[:500]
        agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
        agent = agent_result.scalar_one_or_none()
        if agent:
            agent.status = "CREATED"
            agent.updated_at = datetime.now(timezone.utc)

    await session.commit()
    return {"logged": True, "backtest_id": backtest_id}


@router.post("/{agent_id}/activate", status_code=200)
async def activate_agent(agent_id: str, session: DbSession):
    """Activate an agent for live trading via Claude Code agent."""
    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.status not in ("BACKTEST_COMPLETE", "PAUSED", "CREATED"):
        raise HTTPException(status_code=400, detail=f"Cannot activate agent in status {agent.status}")

    from apps.api.src.services.agent_gateway import gateway
    mgr_result = await gateway.create_analyst(uuid.UUID(agent_id))
    if not mgr_result:
        raise HTTPException(status_code=400, detail="Could not start agent")
    return {"message": "Agent activated", "agent_id": agent_id, "status": "RUNNING", "worker": mgr_result}


@router.get("/{agent_id}/worker-status")
async def get_worker_status(agent_id: str, session: DbSession):
    """Get the Claude Code agent worker status."""
    from apps.api.src.services.agent_gateway import get_agent_status

    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    worker = get_agent_status(agent_id)
    return {
        "agent_id": agent_id,
        "agent_status": agent.status,
        "worker_status": agent.worker_status or "STOPPED",
        "worker_running": worker.get("running", False),
        "session_id": worker.get("session_id"),
    }


@router.get("/{agent_id}/backtest-artifacts")
async def get_backtest_artifacts(agent_id: str, session: DbSession):
    """Return comprehensive backtesting artifacts: all model results, features, preprocessing summary, and available files."""
    import os
    from pathlib import Path

    bt_result = await session.execute(
        select(AgentBacktest)
        .where(AgentBacktest.agent_id == uuid.UUID(agent_id))
        .order_by(desc(AgentBacktest.created_at))
        .limit(1)
    )
    bt = bt_result.scalar_one_or_none()
    if not bt:
        raise HTTPException(status_code=404, detail="No backtest found")

    metrics = bt.metrics or {}

    repo_root = Path(__file__).resolve().parents[4]
    data_dir = repo_root / "data"
    work_dir = data_dir / f"backtest_{agent_id}"
    output_dir = work_dir / "output"

    # Resolve versioned output directory from latest.json
    version_dir = output_dir
    latest_file = work_dir / "latest.json"
    if latest_file.exists():
        import json as _json_latest
        try:
            latest_data = _json_latest.loads(latest_file.read_text())
            vdir = latest_data.get("output_dir", "")
            if vdir and Path(vdir).exists():
                version_dir = Path(vdir)
            else:
                v_num = latest_data.get("version")
                if v_num and (output_dir / f"v{v_num}").exists():
                    version_dir = output_dir / f"v{v_num}"
        except Exception:
            pass
    if version_dir == output_dir:
        for vd in sorted(output_dir.glob("v*"), reverse=True):
            if vd.is_dir():
                version_dir = vd
                break

    def _find_file(*candidates: Path) -> Path | None:
        for c in candidates:
            if c.exists():
                return c
        return None

    feature_names: list[str] = metrics.get("feature_names", [])
    if not feature_names:
        fn_file = _find_file(
            version_dir / "feature_names.json",
            version_dir / "preprocessed" / "feature_names.json",
            work_dir / "feature_names.json",
            work_dir / "preprocessed" / "feature_names.json",
            output_dir / "feature_names.json",
            output_dir / "preprocessed" / "feature_names.json",
        )
        if fn_file:
            import json as _json
            feature_names = _json.loads(fn_file.read_text())
        if not feature_names:
            meta_file = _find_file(
                version_dir / "meta.json",
                version_dir / "preprocessed" / "meta.json",
                work_dir / "preprocessed" / "meta.json",
                work_dir / "meta.json",
                output_dir / "meta.json",
                output_dir / "preprocessed" / "meta.json",
            )
            if meta_file:
                import json as _json
                try:
                    feature_names = _json.loads(meta_file.read_text()).get("feature_columns", [])
                except Exception:
                    pass

    all_model_results: list[dict] = metrics.get("all_model_results", [])
    if not all_model_results:
        import json as _json
        for mdir in [version_dir / "models", work_dir / "models", output_dir / "models"]:
            if mdir.exists():
                for rf in sorted(mdir.glob("*_results.json")):
                    try:
                        all_model_results.append(_json.loads(rf.read_text()))
                    except Exception:
                        pass
                if all_model_results:
                    break

    preprocessing_summary: dict = metrics.get("preprocessing_summary", {})
    if not preprocessing_summary:
        ps_file = _find_file(
            version_dir / "preprocessed" / "preprocessing_summary.json",
            version_dir / "preprocessing_summary.json",
            work_dir / "preprocessed" / "preprocessing_summary.json",
            work_dir / "preprocessing_summary.json",
            output_dir / "preprocessed" / "preprocessing_summary.json",
            output_dir / "preprocessing_summary.json",
        )
        if ps_file:
            import json as _json
            try:
                preprocessing_summary = _json.loads(ps_file.read_text())
            except Exception:
                pass
        if not preprocessing_summary:
            meta_file = _find_file(
                version_dir / "meta.json",
                version_dir / "preprocessed" / "meta.json",
                work_dir / "preprocessed" / "meta.json",
                work_dir / "meta.json",
                output_dir / "meta.json",
            )
            if meta_file:
                import json as _json
                try:
                    meta = _json.loads(meta_file.read_text())
                    preprocessing_summary = {
                        "total_rows": meta.get("total_rows", 0),
                        "train_rows": meta.get("train_rows", 0),
                        "val_rows": meta.get("val_rows", 0),
                        "test_rows": meta.get("test_rows", 0),
                        "feature_count": meta.get("num_features", len(meta.get("feature_columns", []))),
                    }
                except Exception:
                    pass

    explainability: dict = metrics.get("explainability", {})
    if not explainability:
        expl_file = _find_file(
            version_dir / "models" / "explainability.json",
            version_dir / "explainability.json",
            work_dir / "explainability.json",
            work_dir / "models" / "explainability.json",
            output_dir / "models" / "explainability.json",
            output_dir / "explainability.json",
        )
        if expl_file:
            import json as _json
            try:
                explainability = _json.loads(expl_file.read_text())
            except Exception:
                pass

    patterns: list = metrics.get("patterns", [])
    if not patterns:
        pat_file = _find_file(
            version_dir / "models" / "patterns.json",
            version_dir / "patterns.json",
            work_dir / "patterns.json",
            work_dir / "models" / "patterns.json",
            output_dir / "models" / "patterns.json",
            output_dir / "patterns.json",
        )
        if pat_file:
            import json as _json
            try:
                pat_data = _json.loads(pat_file.read_text())
                patterns = pat_data if isinstance(pat_data, list) else pat_data.get("patterns", [])
            except Exception:
                pass

    if not patterns:
        enriched_for_patterns = _find_file(
            version_dir / "enriched.parquet",
            work_dir / "enriched.parquet",
            output_dir / "enriched.parquet",
        )
        if enriched_for_patterns:
            try:
                import pandas as _pd
                import sys
                sys.path.insert(0, str(repo_root / "agents" / "backtesting" / "tools"))
                from discover_patterns import discover_patterns as _discover
                _edf = _pd.read_parquet(enriched_for_patterns)
                if len(_edf) > 0:
                    patterns = _discover(_edf)
            except Exception:
                pass

    downloadable_files: list[dict] = []
    for scan_root in [version_dir, work_dir, output_dir]:
        if scan_root.exists():
            for fpath in sorted(scan_root.rglob("*")):
                if fpath.is_file() and fpath.stat().st_size > 0:
                    rel = fpath.relative_to(work_dir)
                    rel_str = str(rel)
                    if any(d["name"] == rel_str for d in downloadable_files):
                        continue
                    downloadable_files.append({
                        "name": rel_str,
                        "size_bytes": fpath.stat().st_size,
                        "size_human": _human_size(fpath.stat().st_size),
                    })

    # --- Compute summary metrics from files when DB typed columns are null ---
    computed_total_trades = bt.total_trades or 0
    computed_win_rate = bt.win_rate
    computed_total_return = bt.total_return
    computed_sharpe = bt.sharpe_ratio
    computed_drawdown = bt.max_drawdown

    if computed_total_trades == 0 or computed_win_rate is None:
        enriched_file = _find_file(
            version_dir / "enriched.parquet",
            work_dir / "enriched.parquet",
            output_dir / "enriched.parquet",
        )
        if enriched_file:
            try:
                import pandas as _pd
                edf = _pd.read_parquet(enriched_file)
                computed_total_trades = len(edf)
                if "is_profitable" in edf.columns:
                    computed_win_rate = round(float(edf["is_profitable"].mean()), 4)
                if "pnl_pct" in edf.columns:
                    computed_total_return = round(float(edf["pnl_pct"].sum()), 4)
            except Exception:
                pass

    if computed_total_trades == 0 and preprocessing_summary:
        computed_total_trades = preprocessing_summary.get("total_rows", 0)

    if all_model_results and (computed_sharpe is None or computed_drawdown is None):
        best = max(all_model_results, key=lambda r: r.get("auc_roc", 0))
        if computed_sharpe is None:
            computed_sharpe = best.get("sharpe_ratio", 0.0)
        if computed_drawdown is None:
            computed_drawdown = best.get("max_drawdown_pct", 0.0)

    # Persist computed metrics back to DB so the /backtest endpoint also returns them
    needs_update = False
    if (bt.total_trades or 0) == 0 and computed_total_trades > 0:
        bt.total_trades = computed_total_trades
        needs_update = True
    if bt.win_rate is None and computed_win_rate is not None:
        bt.win_rate = computed_win_rate
        needs_update = True
    if bt.total_return is None and computed_total_return is not None:
        bt.total_return = computed_total_return
        needs_update = True
    if bt.sharpe_ratio is None and computed_sharpe is not None:
        bt.sharpe_ratio = computed_sharpe
        needs_update = True
    if bt.max_drawdown is None and computed_drawdown is not None:
        bt.max_drawdown = computed_drawdown
        needs_update = True
    if not bt.metrics and (all_model_results or feature_names or patterns):
        bt.metrics = {
            "all_model_results": all_model_results,
            "feature_names": feature_names,
            "patterns": patterns,
            "preprocessing_summary": preprocessing_summary,
            "explainability": explainability,
            "best_model": all_model_results[0].get("model_name") if all_model_results else None,
            "accuracy": all_model_results[0].get("accuracy") if all_model_results else None,
            "total_trades": computed_total_trades,
            "win_rate": computed_win_rate,
        }
        needs_update = True

    if needs_update:
        try:
            from shared.db.models.agent import Agent as _Agent
            agent_result = await session.execute(
                select(_Agent).where(_Agent.id == uuid.UUID(agent_id))
            )
            agent_row = agent_result.scalar_one_or_none()
            if agent_row:
                if bt.total_trades:
                    agent_row.total_trades = bt.total_trades
                if bt.win_rate is not None:
                    agent_row.win_rate = bt.win_rate
                if all_model_results:
                    best_m = max(all_model_results, key=lambda r: r.get("auc_roc", r.get("accuracy", 0)) or 0)
                    agent_row.model_type = best_m.get("model_name")
                    agent_row.model_accuracy = best_m.get("accuracy")
            await session.commit()
        except Exception:
            pass

    return {
        "backtest_id": str(bt.id),
        "status": bt.status,
        "progress_pct": bt.progress_pct or 0,
        "current_step": bt.current_step,
        "total_trades": computed_total_trades,
        "win_rate": computed_win_rate,
        "sharpe_ratio": computed_sharpe,
        "max_drawdown": computed_drawdown,
        "total_return": computed_total_return,
        "feature_names": feature_names,
        "feature_count": len(feature_names),
        "all_model_results": all_model_results,
        "preprocessing_summary": preprocessing_summary,
        "explainability": explainability,
        "patterns": patterns,
        "downloadable_files": downloadable_files,
        "metrics": metrics,
        "completed_at": bt.completed_at.isoformat() if bt.completed_at else None,
        "created_at": bt.created_at.isoformat() if bt.created_at else None,
    }


def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


@router.get("/{agent_id}/backtest-files/{file_path:path}")
async def download_backtest_file(agent_id: str, file_path: str):
    """Download a raw file from the backtesting work directory."""
    from pathlib import Path
    from fastapi.responses import FileResponse

    repo_root = Path(__file__).resolve().parents[4]
    work_dir = repo_root / "data" / f"backtest_{agent_id}"

    target = (work_dir / file_path).resolve()
    if not str(target).startswith(str(work_dir.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    media_type = "application/octet-stream"
    if target.suffix == ".json":
        media_type = "application/json"
    elif target.suffix == ".csv":
        media_type = "text/csv"

    return FileResponse(target, media_type=media_type, filename=target.name)


@router.get("/{agent_id}/backtest-csv/{file_path:path}")
async def download_backtest_csv(agent_id: str, file_path: str):
    """Convert a .parquet file to CSV on-the-fly and serve it for download."""
    from pathlib import Path
    from fastapi.responses import StreamingResponse
    import io

    repo_root = Path(__file__).resolve().parents[4]
    work_dir = repo_root / "data" / f"backtest_{agent_id}"

    target = (work_dir / file_path).resolve()
    if not str(target).startswith(str(work_dir.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if target.suffix != ".parquet":
        raise HTTPException(status_code=400, detail="Only .parquet files can be converted to CSV")

    try:
        import pandas as pd
        df = pd.read_parquet(target)
        buf = io.StringIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        csv_name = target.stem + ".csv"
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={csv_name}"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to convert: {str(e)[:200]}")


# -- Gateway session listing -----------------------------------------------


@router.get("/gateway/sessions")
async def list_gateway_sessions(session: DbSession):
    """List all active Claude Code agent sessions from the gateway."""
    from apps.api.src.services.agent_gateway import gateway
    sessions = await gateway.list_agents()
    return {"sessions": sessions}


@router.get("/{agent_id}/sessions")
async def get_agent_sessions(agent_id: str, session: DbSession, limit: int = Query(20, ge=1, le=100)):
    """Get session history for a specific agent."""
    from shared.db.models.agent_session import AgentSession
    result = await session.execute(
        select(AgentSession)
        .where(AgentSession.agent_id == uuid.UUID(agent_id))
        .order_by(AgentSession.started_at.desc())
        .limit(limit)
    )
    sessions = result.scalars().all()
    return [
        {
            "id": str(s.id),
            "agent_type": s.agent_type,
            "status": s.status,
            "session_id": s.session_id,
            "working_dir": s.working_dir,
            "started_at": s.started_at.isoformat() if s.started_at else None,
            "last_heartbeat": s.last_heartbeat.isoformat() if s.last_heartbeat else None,
            "stopped_at": s.stopped_at.isoformat() if s.stopped_at else None,
            "error_message": s.error_message,
            "trading_mode": s.trading_mode,
        }
        for s in sessions
    ]


# ---------------------------------------------------------------------------
# Phase 0: Verifiable Alpha CI — run backtest CI on a pending improvement
# ---------------------------------------------------------------------------


class BacktestCIResult(BaseModel):
    """Response model for the run-backtest endpoint."""

    improvement_id: str
    backtest_passed: bool
    backtest_status: str  # "passed" | "failed" | "borderline" | "running" | "pending"
    backtest_metrics: dict[str, Any]
    backtest_run_at: str
    thresholds_missed: list[str]


@router.post(
    "/{agent_id}/improvements/{improvement_id}/run-backtest",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=BacktestCIResult,
)
async def run_improvement_backtest(
    agent_id: str,
    improvement_id: str,
    request: Request,
    session: DbSession,
) -> BacktestCIResult:
    """Run Backtest CI on a single pending improvement rule.

    Auth: requires valid user; IDOR check enforced (owner or admin only).
    Returns 202 Accepted with the CI result immediately (simulated backtest uses
    the most-recent completed AgentBacktest as a proxy — see BacktestCIService).
    """
    from apps.api.src.services.backtest_ci import BacktestCIService

    # Resolve agent
    try:
        agent_uuid = uuid.UUID(agent_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    result = await session.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    # IDOR check
    caller_id = getattr(request.state, "user_id", None)
    is_admin = getattr(request.state, "is_admin", False)
    if str(agent.user_id) != str(caller_id) and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Verify improvement exists
    pending = agent.pending_improvements or {}
    items: list[dict] = pending.get("items", []) if isinstance(pending, dict) else []
    target = next((i for i in items if i.get("id") == improvement_id), None)
    if not target:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Improvement not found"
        )

    # Reject if already running
    if target.get("backtest_status") == "running":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Backtest CI is already running for this improvement",
        )

    # Delegate to BacktestCIService
    svc = BacktestCIService(session)
    try:
        updated = await svc.run_ci_for_improvement(agent_uuid, improvement_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except OverflowError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return BacktestCIResult(
        improvement_id=improvement_id,
        backtest_passed=updated.get("backtest_passed", False),
        backtest_status=updated.get("backtest_status", "failed"),
        backtest_metrics=updated.get("backtest_metrics", {}),
        backtest_run_at=updated.get("backtest_run_at", ""),
        thresholds_missed=updated.get("backtest_thresholds_missed", []),
    )


# ---------------------------------------------------------------------------
# Phase 4: Smart Context — context/latest endpoint
# ---------------------------------------------------------------------------


class ContextSessionResponse(BaseModel):
    id: str
    session_type: str
    signal_symbol: str | None
    token_budget: int
    tokens_used: int
    wiki_entries_injected: int
    trades_injected: int
    manifest_sections_injected: list[str]
    quality_score: float | None
    built_at: str


@router.get("/{agent_id}/context/latest", response_model=ContextSessionResponse)
async def get_latest_context_session(agent_id: str, session: DbSession):
    """Return the most recent ContextSession for this agent.

    Returns 404 if no context sessions exist yet (e.g. ENABLE_SMART_CONTEXT=false).
    """
    from shared.db.models.context_session import ContextSession  # noqa: PLC0415

    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid agent_id")

    stmt = (
        select(ContextSession)
        .where(ContextSession.agent_id == agent_uuid)
        .order_by(desc(ContextSession.built_at))
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No context sessions found. Enable ENABLE_SMART_CONTEXT=true to start recording.",
        )
    return ContextSessionResponse(
        id=str(row.id),
        session_type=row.session_type,
        signal_symbol=row.signal_symbol,
        token_budget=row.token_budget,
        tokens_used=row.tokens_used,
        wiki_entries_injected=row.wiki_entries_injected,
        trades_injected=row.trades_injected,
        manifest_sections_injected=row.manifest_sections_injected or [],
        quality_score=row.quality_score,
        built_at=row.built_at.isoformat() if row.built_at else "",
    )
