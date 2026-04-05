"""
Agent CRUD API routes with Bridge Service integration.

M1.11: Agent management from dashboard.
Reference: PRD Section 3.4, ArchitecturePlan §3, §6.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc

from apps.api.src.deps import DbSession
from shared.db.models.agent import Agent, AgentBacktest
from shared.db.models.connector import ConnectorAgent

router = APIRouter(prefix="/api/v2/agents", tags=["agents"])


class AgentCreate(BaseModel):
    """6-step agent creation wizard payload."""
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., pattern="^(trading|trend|sentiment)$")
    instance_id: str = ""
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
    instance_id: str | None
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

    @classmethod
    def from_model(cls, a: Agent) -> "AgentResponse":
        return cls(
            id=str(a.id),
            name=a.name,
            type=a.type,
            status=a.status,
            instance_id=str(a.instance_id) if a.instance_id else None,
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
        )


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    session: DbSession,
    agent_type: str | None = Query(None, alias="type"),
    status_filter: str | None = Query(None, alias="status"),
    instance_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List agents with optional filters."""
    query = select(Agent).order_by(desc(Agent.created_at))
    if agent_type:
        query = query.where(Agent.type == agent_type)
    if status_filter:
        query = query.where(Agent.status == status_filter)
    if instance_id:
        query = query.where(Agent.instance_id == uuid.UUID(instance_id))
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
async def create_agent(payload: AgentCreate, session: DbSession):
    """
    Create a new agent. Inserts DB rows, then ships backtesting agent to VPS
    and starts the backtesting pipeline via the Agent Gateway.
    """
    agent_type = "trend" if payload.type == "sentiment" else payload.type
    instance_id = uuid.UUID(payload.instance_id) if payload.instance_id else None

    channel_name = (payload.config or {}).get("selected_channel", {}).get("channel_name") if isinstance(payload.config.get("selected_channel"), dict) else None
    analyst_name = payload.name.split(" ")[0] if payload.name else None

    agent_id = uuid.uuid4()
    agent = Agent(
        id=agent_id,
        name=payload.name,
        type=agent_type,
        status="BACKTESTING" if instance_id else "CREATED",
        instance_id=instance_id,
        channel_name=channel_name,
        analyst_name=analyst_name,
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
        status="RUNNING" if instance_id else "PENDING",
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

    if instance_id:
        import asyncio
        asyncio.create_task(
            _ship_and_run_backtest(agent_id, instance_id, backtest.id, payload.config or {})
        )

    return AgentResponse.from_model(agent)


async def _ship_and_run_backtest(agent_id: uuid.UUID, instance_id: uuid.UUID, backtest_id: uuid.UUID, config: dict):
    """Background task: ship backtesting agent to VPS, install Claude if needed, run pipeline."""
    import logging
    from shared.db.engine import get_session as _get_session
    from shared.db.models.claude_code_instance import ClaudeCodeInstance
    from shared.db.models.system_log import SystemLog
    from apps.api.src.services.agent_gateway import gateway

    logger = logging.getLogger(__name__)

    async for session in _get_session():
        try:
            inst_result = await session.execute(
                select(ClaudeCodeInstance).where(ClaudeCodeInstance.id == instance_id)
            )
            inst = inst_result.scalar_one_or_none()
            if not inst:
                raise RuntimeError(f"Instance {instance_id} not found")

            gateway.register_instance(inst.id, inst.host, inst.ssh_port, inst.ssh_username, inst.ssh_key_encrypted)

            async def _log(step: str, msg: str, level: str = "INFO", progress: int | None = None):
                log = SystemLog(
                    id=uuid.uuid4(), source="backtest", level=level, service="agent-gateway",
                    agent_id=str(agent_id), backtest_id=str(backtest_id),
                    message=msg, step=step, progress_pct=progress,
                )
                session.add(log)
                await session.commit()

            await _log("health", "Checking VPS health...", progress=5)
            health = await gateway.check_health(inst.id)
            if not health.reachable:
                raise RuntimeError("VPS is unreachable")

            if not health.claude_installed:
                await _log("install", "Installing Claude Code on VPS...", progress=10)
                install_result = await gateway.install_claude_code(inst.id)
                if install_result.exit_code != 0:
                    raise RuntimeError(f"Claude Code install failed: {install_result.stderr}")
                await _log("install", "Claude Code installed successfully", progress=15)

            await _log("ship", "Shipping backtesting agent to VPS...", progress=20)
            ship_result = await gateway.ship_agent(inst.id, "backtesting", {
                "agent_id": str(agent_id),
                "backtest_id": str(backtest_id),
                "channel_config": config,
            })
            if ship_result.exit_code != 0:
                raise RuntimeError(f"Ship failed: {ship_result.stderr}")

            await _log("ship", "Backtesting agent shipped", progress=25)
            await _log("run", "Starting backtesting pipeline on VPS...", progress=30)

            run_result = await gateway.run_backtesting(inst.id, {
                "agent_id": str(agent_id),
                "backtest_id": str(backtest_id),
                "channel_config": config,
            })

            if run_result.exit_code != 0:
                await _log("run", f"Backtesting failed: {run_result.stderr}", level="ERROR", progress=100)
                bt_result = await session.execute(
                    select(AgentBacktest).where(AgentBacktest.id == backtest_id)
                )
                bt = bt_result.scalar_one_or_none()
                if bt:
                    bt.status = "FAILED"
                    bt.error_message = run_result.stderr[:500] if run_result.stderr else "Pipeline failed"

                ag_result = await session.execute(select(Agent).where(Agent.id == agent_id))
                ag = ag_result.scalar_one_or_none()
                if ag:
                    ag.status = "CREATED"
                await session.commit()
                return

            await _log("run", "Backtesting pipeline completed", progress=100)

            bt_result = await session.execute(
                select(AgentBacktest).where(AgentBacktest.id == backtest_id)
            )
            bt = bt_result.scalar_one_or_none()
            if bt and bt.status == "RUNNING":
                bt.status = "COMPLETED"
                bt.completed_at = datetime.now(timezone.utc)

            ag_result = await session.execute(select(Agent).where(Agent.id == agent_id))
            ag = ag_result.scalar_one_or_none()
            if ag and ag.status == "BACKTESTING":
                ag.status = "BACKTEST_COMPLETE"
            await session.commit()

        except Exception as exc:
            logger.exception("Background backtest failed for agent %s", agent_id)
            try:
                log = SystemLog(
                    id=uuid.uuid4(), source="backtest", level="ERROR", service="agent-gateway",
                    agent_id=str(agent_id), backtest_id=str(backtest_id),
                    message=str(exc)[:500], step="error",
                )
                session.add(log)

                bt_result = await session.execute(select(AgentBacktest).where(AgentBacktest.id == backtest_id))
                bt = bt_result.scalar_one_or_none()
                if bt:
                    bt.status = "FAILED"
                    bt.error_message = str(exc)[:500]

                ag_result = await session.execute(select(Agent).where(Agent.id == agent_id))
                ag = ag_result.scalar_one_or_none()
                if ag:
                    ag.status = "CREATED"
                await session.commit()
            except Exception:
                logger.exception("Failed to record backtest failure")


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
    """Delete an agent from DB and Bridge Service."""
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
    """Pause a running agent."""
    result = await session.execute(
        select(Agent).where(Agent.id == uuid.UUID(agent_id))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    agent.status = "PAUSED"
    await session.commit()
    return {"id": agent_id, "status": "PAUSED"}


@router.post("/{agent_id}/resume")
async def resume_agent(agent_id: str, session: DbSession):
    """Resume a paused agent."""
    result = await session.execute(
        select(Agent).where(Agent.id == uuid.UUID(agent_id))
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    agent.status = "RUNNING"
    await session.commit()
    return {"id": agent_id, "status": "RUNNING"}


class AgentApprovePayload(BaseModel):
    trading_mode: str = "paper"  # "paper" or "live"
    account_id: str | None = None
    stop_loss_pct: float = 2.0
    target_profit_pct: float = 5.0
    max_daily_loss_pct: float = 5.0
    max_position_pct: float = 10.0


@router.post("/{agent_id}/approve")
async def approve_agent(agent_id: str, session: DbSession, payload: AgentApprovePayload | None = None):
    """
    Approve an agent after backtest review. Transitions CREATED/BACKTESTING -> APPROVED.

    Accepts optional body:
      - trading_mode: "paper" | "live"
      - account_id: broker account UUID (required if live)
      - stop_loss_pct: per-trade stop loss %
      - target_profit_pct: per-trade target profit %
      - max_daily_loss_pct: daily loss limit %
      - max_position_pct: max position as % of account
    """
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
                "max_daily_loss_pct": payload.max_daily_loss_pct or (agent.config or {}).get("max_daily_loss_pct", 3.0),
                "max_position_size_pct": payload.max_position_pct or (agent.config or {}).get("max_position_pct", 5.0),
                "stop_loss_pct": payload.stop_loss_pct or (agent.config or {}).get("stop_loss_pct", 2.0),
            },
            "models": {},
            "knowledge": {},
            "credentials": {},
        }

    await session.commit()

    return {"id": agent_id, "status": "APPROVED", "config": agent.config}


@router.post("/{agent_id}/promote")
async def promote_agent(agent_id: str, session: DbSession):
    """Promote an approved agent to live trading. Ships agent to VPS and transitions to RUNNING."""
    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.status not in ("APPROVED", "PAPER", "BACKTEST_COMPLETE"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Only APPROVED/PAPER agents can be promoted, current: {agent.status}")

    ship_result_info: dict[str, Any] = {}
    if agent.instance_id:
        try:
            from shared.db.models.claude_code_instance import ClaudeCodeInstance
            from apps.api.src.services.agent_builder import agent_builder

            inst_result = await session.execute(
                select(ClaudeCodeInstance).where(ClaudeCodeInstance.id == agent.instance_id)
            )
            inst = inst_result.scalar_one_or_none()
            if inst:
                from apps.api.src.services.agent_gateway import gateway
                gateway.register_instance(inst.id, inst.host, inst.ssh_port, inst.ssh_username, inst.ssh_key_encrypted)

                manifest = agent.manifest or {}
                if not manifest.get("identity"):
                    channel = agent.channel_name or agent.name.lower().replace(" ", "-")
                    manifest = {
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
                        "risk": (agent.config or {}).get("risk_params", (agent.config or {}).get("risk", {})),
                        "models": {},
                        "knowledge": {},
                        "credentials": {},
                    }

                ship_res = await agent_builder.ship_agent(manifest, inst.id)
                ship_result_info = {"shipped": ship_res.exit_code == 0, "message": ship_res.stdout or ship_res.stderr}
                if ship_res.exit_code != 0:
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Failed to ship agent to VPS: {ship_res.stderr}",
                    )
        except HTTPException:
            raise
        except Exception as e:
            ship_result_info = {"shipped": False, "message": str(e)[:300]}

    agent.status = "RUNNING"
    agent.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"id": agent_id, "status": "RUNNING", "ship": ship_result_info}


class LiveMessagePayload(BaseModel):
    content: str
    author: str = ""
    channel: str = ""


@router.post("/{agent_id}/process-message")
async def process_live_message(agent_id: str, payload: LiveMessagePayload, session: DbSession):
    """
    Process a live message through the agent's intelligence pipeline.
    Used for real-time signal processing when the agent is in RUNNING mode.
    """
    result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.status != "RUNNING":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Agent is not running, current: {agent.status}")

    # Get intelligence rules from latest backtest
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


@router.post("/{agent_id}/backtest-complete")
async def complete_agent_backtest(agent_id: str, session: DbSession):
    """
    Run the real backtest pipeline: ingest messages, parse signals,
    reconstruct trades, enrich with market data, discover patterns.
    Falls back to simulated metrics if the pipeline fails.
    """
    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.status != "BACKTESTING":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Agent is not backtesting, current: {agent.status}")

    bt_result = await session.execute(
        select(AgentBacktest)
        .where(AgentBacktest.agent_id == agent.id, AgentBacktest.status == "RUNNING")
        .order_by(desc(AgentBacktest.created_at))
        .limit(1)
    )
    bt = bt_result.scalar_one_or_none()
    if not bt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No running backtest found")

    # Try the real pipeline first
    try:
        from services.backtest_runner.src.pipeline import run_backtest_pipeline
        result = await run_backtest_pipeline(
            session=session,
            agent_id=agent.id,
            backtest_id=bt.id,
        )
        if "error" not in result and result.get("total_trades", 0) > 0:
            # Pipeline succeeded and found real trades — metrics already saved
            await session.refresh(bt)
            await session.refresh(agent)
            return {
                "backtest_id": str(bt.id),
                "agent_id": agent_id,
                "status": bt.status,
                "pipeline": "real",
                **result,
            }
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
        return {
            "backtest_id": str(bt.id),
            "agent_id": agent_id,
            "status": "FAILED",
            "error": error_msg,
        }

    now = datetime.now(timezone.utc)
    error_msg = result.get("error", "Pipeline returned no trades")
    bt.status = "FAILED"
    bt.error_message = error_msg
    bt.completed_at = now
    agent.status = "CREATED"
    agent.updated_at = now
    await session.commit()
    return {
        "backtest_id": str(bt.id),
        "agent_id": agent_id,
        "status": "FAILED",
        "error": error_msg,
    }


@router.get("/{agent_id}/backtest-trades")
async def get_backtest_trades(
    agent_id: str,
    session: DbSession,
    limit: int = Query(200, ge=1, le=1000),
):
    """Get all reconstructed trades from the latest backtest for an agent."""
    from shared.db.models.backtest_trade import BacktestTrade

    bt_result = await session.execute(
        select(AgentBacktest)
        .where(AgentBacktest.agent_id == uuid.UUID(agent_id))
        .order_by(desc(AgentBacktest.created_at))
        .limit(1)
    )
    bt = bt_result.scalar_one_or_none()
    if not bt:
        return {"trades": [], "backtest_id": None}

    trades_result = await session.execute(
        select(BacktestTrade)
        .where(BacktestTrade.backtest_id == bt.id)
        .order_by(BacktestTrade.entry_time.asc())
        .limit(limit)
    )
    trades = trades_result.scalars().all()

    return {
        "backtest_id": str(bt.id),
        "trades": [
            {
                "id": str(t.id),
                "ticker": t.ticker,
                "side": t.side,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                "exit_time": t.exit_time.isoformat() if t.exit_time else None,
                "pnl": t.pnl,
                "pnl_pct": t.pnl_pct,
                "holding_period_hours": t.holding_period_hours,
                "is_profitable": t.is_profitable,
                "entry_rsi": t.entry_rsi,
                "entry_macd": t.entry_macd,
                "entry_bollinger_position": t.entry_bollinger_position,
                "entry_volume_ratio": t.entry_volume_ratio,
                "market_vix": t.market_vix,
                "market_spy_change": t.market_spy_change,
                "hour_of_day": t.hour_of_day,
                "day_of_week": t.day_of_week,
                "is_pre_market": t.is_pre_market,
                "pattern_tags": t.pattern_tags,
                "option_flow_sentiment": t.option_flow_sentiment,
            }
            for t in trades
        ],
    }


@router.get("/{agent_id}/logs")
async def get_agent_logs(
    agent_id: str,
    session: DbSession,
    level: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Stream agent logs from DB."""
    from shared.db.models.agent import AgentLog
    query = select(AgentLog).where(AgentLog.agent_id == uuid.UUID(agent_id)).order_by(desc(AgentLog.created_at))
    if level:
        query = query.where(AgentLog.level == level.upper())
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    logs = result.scalars().all()
    return [
        {
            "id": str(log.id),
            "level": log.level,
            "message": log.message,
            "context": log.context,
            "created_at": log.created_at.isoformat() if log.created_at else "",
        }
        for log in logs
    ]


# ── Live Agent Endpoints (Claude Code) ──────────────────────────────────────


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


class ChatMessage(BaseModel):
    content: str


@router.get("/{agent_id}/live-trades")
async def get_live_trades(
    agent_id: str,
    session: DbSession,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=1000),
):
    """Live trade history from a running agent."""
    from shared.db.models.agent_trade import AgentTrade
    query = (
        select(AgentTrade)
        .where(AgentTrade.agent_id == uuid.UUID(agent_id))
        .order_by(desc(AgentTrade.entry_time))
        .limit(limit)
    )
    if status_filter:
        query = query.where(AgentTrade.status == status_filter)
    result = await session.execute(query)
    trades = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "ticker": t.ticker,
            "side": t.side,
            "option_type": t.option_type,
            "strike": t.strike,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "quantity": t.quantity,
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "exit_time": t.exit_time.isoformat() if t.exit_time else None,
            "pnl_dollar": t.pnl_dollar,
            "pnl_pct": t.pnl_pct,
            "status": t.status,
            "model_confidence": t.model_confidence,
            "pattern_matches": t.pattern_matches,
            "reasoning": t.reasoning,
        }
        for t in trades
    ]


@router.post("/{agent_id}/live-trades", status_code=status.HTTP_201_CREATED)
async def report_live_trade(agent_id: str, payload: LiveTradeCreate, session: DbSession):
    """Agent reports a new trade (callback from VPS)."""
    from shared.db.models.agent_trade import AgentTrade
    from datetime import date as date_type

    trade = AgentTrade(
        id=uuid.uuid4(),
        agent_id=uuid.UUID(agent_id),
        ticker=payload.ticker,
        side=payload.side,
        option_type=payload.option_type,
        strike=payload.strike,
        expiry=date_type.fromisoformat(payload.expiry) if payload.expiry else None,
        entry_price=payload.entry_price,
        quantity=payload.quantity,
        entry_time=datetime.now(timezone.utc),
        status="open",
        model_confidence=payload.model_confidence,
        pattern_matches=payload.pattern_matches,
        reasoning=payload.reasoning,
        signal_raw=payload.signal_raw,
        broker_order_id=payload.broker_order_id,
    )
    session.add(trade)

    # Update agent stats
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
        select(AgentTrade)
        .where(AgentTrade.agent_id == uuid.UUID(agent_id), AgentTrade.status == "open")
    )
    trades = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "ticker": t.ticker,
            "side": t.side,
            "entry_price": t.entry_price,
            "quantity": t.quantity,
            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
            "model_confidence": t.model_confidence,
        }
        for t in trades
    ]


@router.get("/{agent_id}/metrics")
async def get_agent_metrics(agent_id: str, session: DbSession):
    """Latest metrics snapshot."""
    from shared.db.models.agent_metric import AgentMetric
    result = await session.execute(
        select(AgentMetric)
        .where(AgentMetric.agent_id == uuid.UUID(agent_id))
        .order_by(desc(AgentMetric.timestamp))
        .limit(1)
    )
    metric = result.scalar_one_or_none()
    if not metric:
        return {"agent_id": agent_id, "metrics": None}
    return {
        "agent_id": agent_id,
        "timestamp": metric.timestamp.isoformat(),
        "portfolio_value": metric.portfolio_value,
        "daily_pnl": metric.daily_pnl,
        "open_positions": metric.open_positions,
        "trades_today": metric.trades_today,
        "win_rate": metric.win_rate,
        "avg_confidence": metric.avg_confidence,
        "signals_processed": metric.signals_processed,
        "tokens_used": metric.tokens_used,
        "status": metric.status,
    }


@router.post("/{agent_id}/metrics")
async def report_agent_metrics(agent_id: str, session: DbSession, payload: dict[str, Any] | None = None):
    """Agent reports metrics (callback from VPS)."""
    from shared.db.models.agent_metric import AgentMetric
    if payload is None:
        payload = {}
    metric = AgentMetric(
        id=uuid.uuid4(),
        agent_id=uuid.UUID(agent_id),
        portfolio_value=payload.get("portfolio_value"),
        daily_pnl=payload.get("daily_pnl"),
        open_positions=payload.get("open_positions"),
        trades_today=payload.get("trades_today"),
        win_rate=payload.get("win_rate"),
        avg_confidence=payload.get("avg_confidence"),
        signals_processed=payload.get("signals_processed"),
        tokens_used=payload.get("tokens_used"),
        status=payload.get("status"),
    )
    session.add(metric)
    await session.commit()
    return {"recorded": True}


@router.get("/{agent_id}/metrics/history")
async def get_agent_metrics_history(
    agent_id: str,
    session: DbSession,
    limit: int = Query(100, ge=1, le=1000),
):
    """Metrics over time for charts."""
    from shared.db.models.agent_metric import AgentMetric
    result = await session.execute(
        select(AgentMetric)
        .where(AgentMetric.agent_id == uuid.UUID(agent_id))
        .order_by(desc(AgentMetric.timestamp))
        .limit(limit)
    )
    metrics = result.scalars().all()
    return [
        {
            "timestamp": m.timestamp.isoformat(),
            "portfolio_value": m.portfolio_value,
            "daily_pnl": m.daily_pnl,
            "open_positions": m.open_positions,
            "trades_today": m.trades_today,
            "win_rate": m.win_rate,
        }
        for m in reversed(metrics)
    ]


@router.get("/{agent_id}/chat")
async def get_agent_chat(agent_id: str, session: DbSession, limit: int = Query(50, ge=1, le=200)):
    """Get chat history with an agent, including message_type and metadata."""
    from shared.db.models.agent_chat import AgentChatMessage
    result = await session.execute(
        select(AgentChatMessage)
        .where(AgentChatMessage.agent_id == uuid.UUID(agent_id))
        .order_by(AgentChatMessage.created_at.asc())
        .limit(limit)
    )
    messages = result.scalars().all()
    return [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "message_type": getattr(m, "message_type", "text") or "text",
            "metadata": getattr(m, "extra_data", {}) or {},
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


@router.post("/{agent_id}/chat")
async def send_agent_chat(agent_id: str, payload: dict[str, Any], session: DbSession):
    """Send a message to the agent via SSH and return the response.
    
    Accepts:
      - message (str): the message text
      - message_type (str): "text", "trade_request", "rule_change", "command" (default "text")
      - metadata (dict): additional structured data
    """
    from shared.db.models.agent_chat import AgentChatMessage

    content = payload.get("message", payload.get("content", ""))
    if not content:
        raise HTTPException(status_code=400, detail="message is required")

    msg_type = payload.get("message_type", "text")
    msg_metadata = payload.get("metadata", {})

    user_msg = AgentChatMessage(
        id=uuid.uuid4(),
        agent_id=uuid.UUID(agent_id),
        role="user",
        content=content,
        message_type=msg_type,
        extra_data=msg_metadata,
    )
    session.add(user_msg)

    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    response_text = "Agent is not connected to a VPS instance."
    response_type = "text"
    response_metadata: dict[str, Any] = {}

    if agent.instance_id:
        try:
            from shared.db.models.claude_code_instance import ClaudeCodeInstance
            inst_result = await session.execute(
                select(ClaudeCodeInstance).where(ClaudeCodeInstance.id == agent.instance_id)
            )
            inst = inst_result.scalar_one_or_none()
            if inst:
                from apps.api.src.services.agent_gateway import gateway
                gateway.register_instance(inst.id, inst.host, inst.ssh_port, inst.ssh_username, inst.ssh_key_encrypted)
                agent_name = agent.channel_name or agent.name.lower().replace(" ", "-")

                check = await gateway.run_command(inst.id, f"test -d ~/agents/live/{agent_name} && echo EXISTS || echo MISSING", timeout=15)
                if "MISSING" in (check.stdout or ""):
                    try:
                        from apps.api.src.services.agent_builder import agent_builder
                        manifest = agent.manifest or {}
                        if not manifest.get("identity"):
                            manifest = {
                                "version": "1.0", "template": "live-trader-v1",
                                "identity": {"name": agent.name, "channel": agent_name, "analyst": agent.analyst_name or "", "character": "balanced-intraday"},
                                "rules": (agent.config or {}).get("rules", []),
                                "modes": (agent.config or {}).get("modes", {}),
                                "risk": (agent.config or {}).get("risk_params", (agent.config or {}).get("risk", {})),
                                "models": {}, "knowledge": {}, "credentials": {},
                            }
                        ship_res = await agent_builder.ship_agent(manifest, inst.id)
                        if ship_res.exit_code != 0:
                            response_text = f"Agent workspace not found on VPS and auto-deploy failed: {ship_res.stderr}"
                        else:
                            response_text = await gateway.send_message(inst.id, agent_name, content)
                    except Exception as ship_err:
                        response_text = f"Agent workspace not found on VPS and auto-deploy failed: {str(ship_err)[:200]}"
                else:
                    response_text = await gateway.send_message(inst.id, agent_name, content)

                if msg_type == "trade_request":
                    response_type = "trade_proposal"
                    response_metadata = {"original_request": content}
        except Exception as e:
            response_text = f"Failed to reach agent: {str(e)[:200]}"

    agent_msg = AgentChatMessage(
        id=uuid.uuid4(),
        agent_id=uuid.UUID(agent_id),
        role="agent",
        content=response_text,
        message_type=response_type,
        extra_data=response_metadata,
    )
    session.add(agent_msg)
    await session.commit()

    return {
        "user_message": content,
        "agent_response": response_text,
        "message_type": response_type,
        "metadata": response_metadata,
    }


@router.post("/{agent_id}/heartbeat")
async def agent_heartbeat(agent_id: str, session: DbSession, payload: dict[str, Any] | None = None):
    """Agent reports heartbeat (callback from VPS)."""
    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if payload:
        if "status" in payload:
            agent.status = payload["status"]
        if "signals_processed" in payload:
            agent.last_signal_at = datetime.now(timezone.utc)

    agent.updated_at = datetime.now(timezone.utc)
    await session.commit()
    return {"ack": True}


@router.post("/{agent_id}/command")
async def send_agent_command(agent_id: str, session: DbSession, payload: dict[str, Any] | None = None):
    """Send operational command to agent (pause/resume/switch_mode/close_position/update_config/approve_trade)."""
    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    body = payload or {}
    action = body.get("action", body.get("command", "status"))

    if action == "pause":
        agent.status = "PAUSED"
        await session.commit()
        return {"action": "pause", "result": "Agent paused"}

    if action == "resume":
        agent.status = "RUNNING"
        await session.commit()
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

        if agent.instance_id:
            try:
                from apps.api.src.services.agent_builder import agent_builder
                channel = agent.channel_name or agent.name.lower().replace(" ", "-")
                await agent_builder.update_agent_config(agent.instance_id, channel, {"current_mode": new_mode})
            except Exception:
                pass

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

        if agent.instance_id:
            try:
                from apps.api.src.services.agent_builder import agent_builder
                channel = agent.channel_name or agent.name.lower().replace(" ", "-")
                await agent_builder.update_agent_config(agent.instance_id, channel, body.get("config", {}))
            except Exception:
                pass

        return {"action": "update_config", "result": "Config updated", "rules_version": agent.rules_version}

    if action == "close_position":
        ticker = body.get("ticker", "")
        pct = body.get("pct", 100)
        if not ticker:
            raise HTTPException(status_code=400, detail="ticker is required for close_position")

        if agent.instance_id:
            try:
                from apps.api.src.services.agent_gateway import gateway
                from shared.db.models.claude_code_instance import ClaudeCodeInstance
                inst_result = await session.execute(select(ClaudeCodeInstance).where(ClaudeCodeInstance.id == agent.instance_id))
                inst = inst_result.scalar_one_or_none()
                if inst:
                    gateway.register_instance(inst.id, inst.host, inst.ssh_port, inst.ssh_username, inst.ssh_key_encrypted)
                    agent_name = agent.channel_name or agent.name.lower().replace(" ", "-")
                    msg = f"Close {pct}% of position in {ticker} immediately."
                    response = await gateway.send_message(inst.id, agent_name, msg)
                    return {"action": "close_position", "result": response}
            except Exception as e:
                return {"action": "close_position", "result": f"Failed: {str(e)[:200]}"}

        return {"action": "close_position", "result": "Agent not connected to VPS"}

    if action == "approve_trade":
        trade_data = body.get("trade", {})
        if not trade_data:
            raise HTTPException(status_code=400, detail="trade is required for approve_trade")

        if agent.instance_id:
            try:
                from apps.api.src.services.agent_gateway import gateway
                from shared.db.models.claude_code_instance import ClaudeCodeInstance
                inst_result = await session.execute(select(ClaudeCodeInstance).where(ClaudeCodeInstance.id == agent.instance_id))
                inst = inst_result.scalar_one_or_none()
                if inst:
                    gateway.register_instance(inst.id, inst.host, inst.ssh_port, inst.ssh_username, inst.ssh_key_encrypted)
                    agent_name = agent.channel_name or agent.name.lower().replace(" ", "-")
                    import json as _json
                    msg = f"APPROVED TRADE: {_json.dumps(trade_data)}. Execute this trade now."
                    response = await gateway.send_message(inst.id, agent_name, msg)
                    return {"action": "approve_trade", "result": response}
            except Exception as e:
                return {"action": "approve_trade", "result": f"Failed: {str(e)[:200]}"}

        return {"action": "approve_trade", "result": "Agent not connected to VPS"}

    return {"action": action, "result": "Unknown action"}


# ── Manifest CRUD ──────────────────────────────────────────────────────────


@router.get("/{agent_id}/manifest")
async def get_agent_manifest(agent_id: str, session: DbSession):
    """Return the agent's current manifest (rules, modes, risk, knowledge, models)."""
    agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    manifest = agent.manifest or {}

    if not manifest and agent.config:
        manifest = {
            "version": "1.0",
            "template": "live-trader-v1",
            "identity": {
                "name": agent.name,
                "channel": agent.channel_name or "",
                "analyst": agent.analyst_name or "",
                "character": "balanced-intraday",
            },
            "rules": (agent.config or {}).get("rules", []),
            "modes": (agent.config or {}).get("modes", {}),
            "risk": (agent.config or {}).get("risk_params", (agent.config or {}).get("risk", {})),
            "models": {
                "primary": agent.model_type or "unknown",
                "accuracy": agent.model_accuracy or 0,
            },
            "tools": [],
            "skills": [],
            "knowledge": {},
        }

    return {
        "agent_id": agent_id,
        "manifest": manifest,
        "current_mode": agent.current_mode,
        "rules_version": agent.rules_version,
    }


@router.put("/{agent_id}/manifest")
async def update_agent_manifest(agent_id: str, payload: dict[str, Any], session: DbSession):
    """Update the agent's manifest (rules, modes, risk). Increments rules_version if rules changed."""
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

    if agent.instance_id:
        try:
            from apps.api.src.services.agent_builder import agent_builder
            channel = agent.channel_name or agent.name.lower().replace(" ", "-")
            config_patch = {}
            if "modes" in payload:
                config_patch["modes"] = payload["modes"]
            if "risk" in payload:
                config_patch["risk_params"] = payload["risk"]
            if config_patch:
                await agent_builder.update_agent_config(agent.instance_id, channel, config_patch)
        except Exception:
            pass

    return {
        "agent_id": agent_id,
        "manifest": agent.manifest,
        "rules_version": agent.rules_version,
    }


# ── Backtest Progress Callback ─────────────────────────────────────────────


class BacktestProgressPayload(BaseModel):
    step: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1)
    progress_pct: int | None = Field(default=None, ge=0, le=100)
    level: str = Field(default="INFO", pattern="^(DEBUG|INFO|WARN|ERROR)$")
    metrics: dict[str, Any] | None = None
    status: str | None = None


@router.post("/{agent_id}/backtest-progress", status_code=201)
async def report_backtest_progress(agent_id: str, payload: BacktestProgressPayload, session: DbSession):
    """Callback from VPS backtesting agent to report step-by-step progress."""
    from shared.db.models.system_log import SystemLog

    bt_result = await session.execute(
        select(AgentBacktest)
        .where(AgentBacktest.agent_id == uuid.UUID(agent_id), AgentBacktest.status == "RUNNING")
        .order_by(desc(AgentBacktest.created_at))
        .limit(1)
    )
    bt = bt_result.scalar_one_or_none()
    backtest_id = str(bt.id) if bt else None

    log = SystemLog(
        id=uuid.uuid4(),
        source="backtest",
        level=payload.level,
        service="backtesting-agent",
        agent_id=agent_id,
        backtest_id=backtest_id,
        message=payload.message,
        step=payload.step,
        progress_pct=payload.progress_pct,
        details=payload.metrics or {},
    )
    session.add(log)

    if bt and payload.metrics:
        bt.metrics = {**(bt.metrics or {}), **payload.metrics}

    if payload.status == "COMPLETED" and bt:
        bt.status = "COMPLETED"
        bt.completed_at = datetime.now(timezone.utc)
        agent_result = await session.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
        agent = agent_result.scalar_one_or_none()
        if agent:
            agent.status = "BACKTEST_COMPLETE"
            agent.updated_at = datetime.now(timezone.utc)

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
