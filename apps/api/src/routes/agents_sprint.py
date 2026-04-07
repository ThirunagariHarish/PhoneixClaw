"""Phase P sprint — new per-agent endpoints grouped in one router to keep
agents.py from growing unmanageably.

Endpoints:
    GET   /api/v2/agents/{id}/channel-messages       P3
    GET   /api/v2/agents/{id}/logs                   P2 (DB read from agent_logs)
    GET   /api/v2/agents/{id}/logs/stream            P2 (SSE live tail)
    POST  /api/v2/agents/{id}/heartbeat              P4
    GET   /api/v2/agents/{id}/tasks                  P5
    GET   /api/v2/agents/{id}/automations            P5
    GET   /api/v2/agents/{id}/crons                  P11
    POST  /api/v2/agents/{id}/crons                  P11
    DELETE /api/v2/agents/{id}/crons/{cron_id}       P11
    GET   /api/v2/agents/{id}/live-metrics           P7 (Sharpe / DD / WR)
    GET   /api/v2/agents/{id}/equity-curve           P6
    GET   /api/v2/portfolio/equity-curve             P6 (global)
    POST  /api/v2/agents/spawn-typed                 P1
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, select, text

from apps.api.src.deps import DbSession
from shared.db.models.agent import Agent
from shared.db.models.channel_message import ChannelMessage
from shared.db.models.connector import ConnectorAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/agents", tags=["agents_sprint"])
portfolio_router = APIRouter(prefix="/api/v2/portfolio", tags=["portfolio"])


# ---------------------------------------------------------------------------
# P3: Raw channel messages
# ---------------------------------------------------------------------------
@router.get("/{agent_id}/channel-messages")
async def get_channel_messages(
    agent_id: uuid.UUID,
    limit: int = Query(200, le=1000),
    since: datetime | None = None,
    session: DbSession = None,
):
    """Return raw Discord/Reddit/Twitter messages from every connector this agent
    is subscribed to via connector_agents."""
    sub_q = select(ConnectorAgent.connector_id).where(
        ConnectorAgent.agent_id == agent_id,
        ConnectorAgent.is_active.is_(True),
    )
    sub_rows = (await session.execute(sub_q)).all()
    connector_ids = [r[0] for r in sub_rows]
    if not connector_ids:
        return {"messages": [], "count": 0}

    q = (
        select(ChannelMessage)
        .where(ChannelMessage.connector_id.in_(connector_ids))
        .order_by(ChannelMessage.posted_at.desc())
        .limit(limit)
    )
    if since:
        q = q.where(ChannelMessage.posted_at >= since)
    rows = (await session.execute(q)).scalars().all()
    messages = [
        {
            "id": str(m.id),
            "connector_id": str(m.connector_id),
            "channel": m.channel,
            "author": m.author,
            "content": m.content,
            "message_type": m.message_type,
            "tickers": m.tickers_mentioned or [],
            "posted_at": m.posted_at.isoformat() if m.posted_at else None,
        }
        for m in rows
    ]
    return {"messages": messages, "count": len(messages)}


# ---------------------------------------------------------------------------
# P2: Logs (polling + SSE stream)
# ---------------------------------------------------------------------------
@router.get("/{agent_id}/logs")
async def get_agent_logs(
    agent_id: uuid.UUID,
    level: str | None = None,
    limit: int = Query(200, le=2000),
    since: datetime | None = None,
    session: DbSession = None,
):
    """Read from agent_logs (preferred) with a fallback to system_logs."""
    rows: list[dict] = []
    try:
        q = text(
            "SELECT id, level, source, message, created_at FROM agent_logs "
            "WHERE agent_id = :aid "
            + (" AND level = :lvl " if level else "")
            + (" AND created_at >= :since " if since else "")
            + " ORDER BY created_at DESC LIMIT :lim"
        )
        params = {"aid": str(agent_id), "lim": limit}
        if level:
            params["lvl"] = level.lower()
        if since:
            params["since"] = since
        res = await session.execute(q, params)
        rows = [
            {
                "id": int(r[0]),
                "level": r[1],
                "source": r[2],
                "message": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
            }
            for r in res.all()
        ]
    except Exception as exc:
        logger.debug("[agents_sprint] agent_logs read failed, falling back: %s", exc)
        # Fallback: system_logs filtered by agent_id JSON
        try:
            q = text(
                "SELECT id, level, source, message, created_at FROM system_logs "
                "WHERE agent_id = :aid ORDER BY created_at DESC LIMIT :lim"
            )
            res = await session.execute(q, {"aid": str(agent_id), "lim": limit})
            rows = [
                {
                    "id": int(r[0]),
                    "level": r[1],
                    "source": r[2],
                    "message": r[3],
                    "created_at": r[4].isoformat() if r[4] else None,
                }
                for r in res.all()
            ]
        except Exception:
            rows = []
    return {"logs": rows, "count": len(rows)}


@router.get("/{agent_id}/logs/stream")
async def stream_agent_logs(agent_id: uuid.UUID, request: Request):
    """SSE endpoint — tails agent_logs for the given agent.

    Poll-based implementation: DB cursor every 1s, yields new rows as SSE events.
    Simpler than Redis pub/sub and works even when the agent writes via direct DB.
    """
    from shared.db.engine import get_session

    async def event_gen():
        last_id: int = 0
        # Initial cursor: current max id so we only tail NEW rows
        async for s in get_session():
            try:
                res = await s.execute(
                    text("SELECT COALESCE(MAX(id), 0) FROM agent_logs WHERE agent_id = :aid"),
                    {"aid": str(agent_id)},
                )
                last_id = int(res.scalar() or 0)
            except Exception:
                last_id = 0
            break

        while True:
            if await request.is_disconnected():
                return
            try:
                async for s in get_session():
                    res = await s.execute(
                        text(
                            "SELECT id, level, source, message, created_at FROM agent_logs "
                            "WHERE agent_id = :aid AND id > :last "
                            "ORDER BY id ASC LIMIT 100"
                        ),
                        {"aid": str(agent_id), "last": last_id},
                    )
                    rows = res.all()
                    for r in rows:
                        last_id = max(last_id, int(r[0]))
                        payload = {
                            "id": int(r[0]),
                            "level": r[1],
                            "source": r[2],
                            "message": r[3],
                            "created_at": r[4].isoformat() if r[4] else None,
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                    break
            except Exception as exc:
                yield f"event: error\ndata: {json.dumps({'error': str(exc)[:120]})}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# P4: Heartbeat
# ---------------------------------------------------------------------------
class HeartbeatBody(BaseModel):
    status: str | None = None
    message: str | None = None
    # Extra fields sent by report_to_phoenix.py in live-trader agents
    signals_processed: int | None = None
    trades_today: int | None = None
    timestamp: str | None = None


@router.post("/{agent_id}/heartbeat")
async def post_heartbeat(
    agent_id: uuid.UUID,
    body: HeartbeatBody,
    session: DbSession = None,
):
    """Agent-auth endpoint: updates last_heartbeat + optional status.

    Called by each agent's background heartbeat thread every ~60s.
    """
    from shared.db.models.agent_session import AgentSession

    now = datetime.now(timezone.utc)

    # Update the latest running session
    res = await session.execute(
        select(AgentSession)
        .where(AgentSession.agent_id == agent_id)
        .order_by(AgentSession.started_at.desc())
        .limit(1)
    )
    sess = res.scalar_one_or_none()
    if sess:
        sess.last_heartbeat = now
        if body.status:
            sess.status = body.status

    # Also update the agent row so the list endpoint can derive runtime_status
    res = await session.execute(select(Agent).where(Agent.id == agent_id))
    agent = res.scalar_one_or_none()
    if agent:
        try:
            agent.last_activity_at = now
            agent.runtime_status = "alive"
        except Exception:
            pass

    await session.commit()
    return {"ok": True, "agent_id": str(agent_id), "at": now.isoformat()}


# ---------------------------------------------------------------------------
# P5: Per-agent tasks + automations
# ---------------------------------------------------------------------------
@router.get("/{agent_id}/tasks")
async def list_agent_tasks(
    agent_id: uuid.UUID,
    status_filter: str | None = None,
    session: DbSession = None,
):
    from shared.db.models.task import Task

    q = select(Task).where(Task.agent_id == agent_id)
    if status_filter:
        q = q.where(Task.status == status_filter)
    q = q.order_by(Task.created_at.desc() if hasattr(Task, "created_at") else Task.id.desc())
    rows = (await session.execute(q)).scalars().all()
    return {
        "tasks": [
            {
                "id": str(t.id),
                "title": getattr(t, "title", None),
                "status": getattr(t, "status", None),
                "priority": getattr(t, "priority", None),
                "due_date": t.due_date.isoformat() if getattr(t, "due_date", None) else None,
            }
            for t in rows
        ],
        "count": len(rows),
    }


@router.get("/{agent_id}/automations")
async def list_agent_automations(
    agent_id: uuid.UUID,
    session: DbSession = None,
):
    from shared.db.models.task import Automation

    try:
        q = select(Automation).where(Automation.agent_id == agent_id) \
            if hasattr(Automation, "agent_id") else select(Automation)
        rows = (await session.execute(q)).scalars().all()
    except Exception as exc:
        return {"automations": [], "error": str(exc)[:200]}

    return {
        "automations": [
            {
                "id": str(a.id),
                "name": getattr(a, "name", None),
                "cron_expression": getattr(a, "cron_expression", None),
                "natural_language": getattr(a, "natural_language", None),
                "is_active": getattr(a, "is_active", True),
                "last_run_at": a.last_run_at.isoformat() if getattr(a, "last_run_at", None) else None,
                "next_run_at": a.next_run_at.isoformat() if getattr(a, "next_run_at", None) else None,
                "run_count": getattr(a, "run_count", 0),
            }
            for a in rows
        ],
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# P11: Per-agent crons
# ---------------------------------------------------------------------------
class AgentCronCreate(BaseModel):
    name: str
    cron_expression: str
    action_type: str = "prompt"
    action_payload: dict | None = None
    enabled: bool = True


@router.get("/{agent_id}/crons")
async def list_agent_crons(agent_id: uuid.UUID, session: DbSession = None):
    try:
        res = await session.execute(
            text("SELECT id, name, cron_expression, action_type, action_payload, "
                 "enabled, last_run_at, next_run_at, run_count FROM agent_crons "
                 "WHERE agent_id = :aid ORDER BY created_at DESC"),
            {"aid": str(agent_id)},
        )
        rows = res.all()
    except Exception:
        rows = []
    return {
        "crons": [
            {
                "id": r[0],
                "name": r[1],
                "cron_expression": r[2],
                "action_type": r[3],
                "action_payload": r[4],
                "enabled": r[5],
                "last_run_at": r[6].isoformat() if r[6] else None,
                "next_run_at": r[7].isoformat() if r[7] else None,
                "run_count": r[8] or 0,
            }
            for r in rows
        ]
    }


@router.post("/{agent_id}/crons")
async def create_agent_cron(
    agent_id: uuid.UUID,
    body: AgentCronCreate,
    session: DbSession = None,
):
    cron_id = uuid.uuid4().hex
    try:
        await session.execute(
            text(
                "INSERT INTO agent_crons (id, agent_id, name, cron_expression, "
                "action_type, action_payload, enabled) VALUES "
                "(:id, :aid, :name, :cron, :at, :payload, :enabled)"
            ),
            {
                "id": cron_id,
                "aid": str(agent_id),
                "name": body.name,
                "cron": body.cron_expression,
                "at": body.action_type,
                "payload": json.dumps(body.action_payload or {}),
                "enabled": body.enabled,
            },
        )
        await session.commit()
    except Exception as exc:
        raise HTTPException(500, str(exc)[:300])

    # Best-effort register with the live scheduler
    try:
        from apps.api.src.services.scheduler import register_agent_cron
        register_agent_cron(cron_id, str(agent_id), body.cron_expression,
                            body.action_type, body.action_payload or {})
    except Exception:
        pass

    return {"id": cron_id, "status": "created"}


@router.delete("/{agent_id}/crons/{cron_id}")
async def delete_agent_cron(
    agent_id: uuid.UUID,
    cron_id: str,
    session: DbSession = None,
):
    try:
        await session.execute(
            text("DELETE FROM agent_crons WHERE id = :id AND agent_id = :aid"),
            {"id": cron_id, "aid": str(agent_id)},
        )
        await session.commit()
    except Exception as exc:
        raise HTTPException(500, str(exc)[:300])

    try:
        from apps.api.src.services.scheduler import unregister_agent_cron
        unregister_agent_cron(cron_id)
    except Exception:
        pass

    return {"ok": True}


# ---------------------------------------------------------------------------
# P6: Equity curve (per-agent + global)
# ---------------------------------------------------------------------------
def _compute_equity_curve(trades: list[dict], starting_capital: float = 100_000.0) -> list[dict]:
    """Build a Robinhood-style equity curve from a list of sorted trades."""
    if not trades:
        return []
    equity = starting_capital
    high_water = starting_capital
    curve: list[dict] = []
    for t in trades:
        pnl = float(t.get("pnl_dollar") or t.get("pnl") or 0.0)
        equity += pnl
        high_water = max(high_water, equity)
        dd_pct = (equity - high_water) / high_water if high_water > 0 else 0.0
        curve.append({
            "timestamp": t.get("closed_at") or t.get("timestamp"),
            "equity": round(equity, 2),
            "high_water_mark": round(high_water, 2),
            "drawdown_pct": round(dd_pct, 4),
            "pnl": round(pnl, 2),
            "symbol": t.get("symbol") or t.get("ticker"),
        })
    return curve


@router.get("/{agent_id}/equity-curve")
async def get_agent_equity_curve(
    agent_id: uuid.UUID,
    days: int = 30,
    session: DbSession = None,
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        from shared.db.models.agent_trade import AgentTrade
        res = await session.execute(
            select(AgentTrade)
            .where(and_(
                AgentTrade.agent_id == agent_id,
                AgentTrade.created_at >= since,
            ))
            .order_by(AgentTrade.created_at.asc())
        )
        trades = [
            {
                "symbol": t.symbol,
                "pnl_dollar": float(t.pnl_dollar or 0),
                "closed_at": t.closed_at.isoformat() if getattr(t, "closed_at", None)
                             else (t.created_at.isoformat() if t.created_at else None),
            }
            for t in res.scalars().all()
        ]
    except Exception:
        trades = []

    curve = _compute_equity_curve(trades)
    return {"curve": curve, "starting_capital": 100_000.0, "days": days}


@portfolio_router.get("/equity-curve")
async def get_global_equity_curve(days: int = 30, session: DbSession = None):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        from shared.db.models.agent_trade import AgentTrade
        res = await session.execute(
            select(AgentTrade)
            .where(AgentTrade.created_at >= since)
            .order_by(AgentTrade.created_at.asc())
        )
        trades = [
            {
                "symbol": t.symbol,
                "pnl_dollar": float(t.pnl_dollar or 0),
                "closed_at": t.closed_at.isoformat() if getattr(t, "closed_at", None)
                             else (t.created_at.isoformat() if t.created_at else None),
            }
            for t in res.scalars().all()
        ]
    except Exception:
        trades = []

    curve = _compute_equity_curve(trades)
    return {"curve": curve, "starting_capital": 100_000.0, "days": days}


# ---------------------------------------------------------------------------
# P7: Live metrics (Sharpe / Max DD / Win rate)
# ---------------------------------------------------------------------------
@router.get("/{agent_id}/live-metrics")
async def get_live_metrics(
    agent_id: uuid.UUID,
    days: int = 30,
    session: DbSession = None,
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        from shared.db.models.agent_trade import AgentTrade
        res = await session.execute(
            select(AgentTrade)
            .where(and_(
                AgentTrade.agent_id == agent_id,
                AgentTrade.created_at >= since,
            ))
            .order_by(AgentTrade.created_at.asc())
        )
        trades = list(res.scalars().all())
    except Exception:
        trades = []

    try:
        from shared.metrics.portfolio_math import current_drawdown, max_drawdown, rolling_sharpe
    except Exception:
        return {
            "sharpe_30d": 0.0, "sharpe_all": 0.0,
            "max_drawdown_pct": 0.0, "current_drawdown_pct": 0.0,
            "win_rate": 0.0, "total_trades": 0,
        }

    pnls = [float(t.pnl_dollar or 0) for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    total = len(pnls)
    win_rate = (wins / total) if total else 0.0

    equity_curve = []
    equity = 100_000.0
    peak = equity
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        equity_curve.append(equity)

    return {
        "sharpe_30d": round(rolling_sharpe(pnls, window=30), 3),
        "sharpe_all": round(rolling_sharpe(pnls, window=len(pnls) or 1), 3),
        "max_drawdown_pct": round(max_drawdown(equity_curve) * 100, 2),
        "current_drawdown_pct": round(current_drawdown(equity_curve) * 100, 2),
        "win_rate": round(win_rate, 4),
        "total_trades": total,
    }


# ---------------------------------------------------------------------------
# P1: Spawn typed agent
# ---------------------------------------------------------------------------
class SpawnTypedBody(BaseModel):
    name: str
    type: str  # analyst | unusual_whales | social_sentiment | strategy | supervisor
    config: dict | None = None


@router.post("/spawn-typed")
async def spawn_typed(body: SpawnTypedBody, session: DbSession = None):
    from apps.api.src.services.agent_gateway import gateway

    kind = body.type.lower().strip()
    try:
        if kind == "supervisor":
            agent_id = await gateway.create_supervisor_agent()
            return {"agent_id": str(agent_id), "type": kind, "status": "starting"}
        if kind == "analyst":
            raise HTTPException(400, "Analyst agents are auto-created after a successful backtest")
        # Specialized types: unusual_whales / social_sentiment / strategy
        if hasattr(gateway, "create_specialized_agent"):
            # Create the Agent DB record first — gateway.create_specialized_agent
            # expects the record to already exist so it can read name/config.
            from shared.db.engine import get_session as _get_session
            from datetime import datetime, timezone as _tz
            new_id = uuid.uuid4()
            now = datetime.now(_tz.utc)
            async for db in _get_session():
                new_agent = Agent(
                    id=new_id,
                    name=body.name,
                    type=kind,
                    status="RUNNING",
                    source="spawn-typed",
                    config=body.config or {},
                    manifest={},
                    pending_improvements={},
                    created_at=now,
                    updated_at=now,
                )
                db.add(new_agent)
                await db.commit()
            agent_id = await gateway.create_specialized_agent(
                agent_id=new_id, agent_type=kind, config=body.config or {}
            )
            return {"agent_id": str(new_id), "type": kind, "status": "starting"}
        raise HTTPException(400, f"Unknown agent type: {kind}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc)[:400])
