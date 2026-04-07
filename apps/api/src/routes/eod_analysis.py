"""End-of-day analysis endpoint.

Called by the scheduler at 16:45 ET weekdays. For each running agent:
1. Enriches trade_signals with outcome prices (1h, 4h, EOD) via yfinance
2. Flags rejected signals where price moved favorably as missed opportunities
3. Computes per-agent daily metrics
4. Dispatches a WhatsApp summary via NotificationDispatcher

The endpoint is also callable manually via:
    POST /api/v2/agents/eod-analysis
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, time, timezone

from fastapi import APIRouter
from sqlalchemy import select, func

from apps.api.src.deps import DbSession
from shared.db.engine import get_session
from shared.db.models.agent import Agent
from shared.db.models.agent_trade import AgentTrade

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/agents", tags=["eod-analysis"])


async def run_eod_analysis() -> dict:
    """Main EOD analysis entrypoint. Returns a summary dict."""
    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "agents_analyzed": 0,
        "trades_today": 0,
        "signals_enriched": 0,
        "missed_opportunities": 0,
        "per_agent": [],
        "errors": [],
    }

    today_start = datetime.combine(
        datetime.now(timezone.utc).date(), time.min
    ).replace(tzinfo=timezone.utc)

    # Collect data per agent
    async for session in get_session():
        # Agents that were active today (have trades or signals)
        agents_result = await session.execute(
            select(Agent).where(Agent.status.in_(["RUNNING", "PAPER", "APPROVED"]))
        )
        agents = list(agents_result.scalars().all())
        summary["agents_analyzed"] = len(agents)

        for agent in agents:
            try:
                agent_summary = await _analyze_agent(
                    session, agent, today_start, summary
                )
                summary["per_agent"].append(agent_summary)
            except Exception as exc:
                logger.exception("EOD analysis failed for %s", agent.id)
                summary["errors"].append({"agent_id": str(agent.id), "error": str(exc)[:300]})

    # Enrich trade_signals with outcomes (if the table exists)
    try:
        enriched = await _enrich_trade_signals(today_start)
        summary["signals_enriched"] = enriched["enriched"]
        summary["missed_opportunities"] = enriched["missed"]
    except Exception as exc:
        logger.warning("trade_signals enrichment skipped: %s", exc)

    # Dispatch consolidated WhatsApp summary
    try:
        body = _format_summary_for_notification(summary)
        from apps.api.src.services.notification_dispatcher import notification_dispatcher
        await notification_dispatcher.dispatch(
            event_type="info",
            agent_id=None,
            title="Phoenix EOD Analysis",
            body=body,
            channels=["whatsapp", "ws", "db"],
        )
        summary["notification_sent"] = True
    except Exception as exc:
        logger.warning("EOD notification dispatch failed: %s", exc)
        summary["notification_sent"] = False

    summary["completed_at"] = datetime.now(timezone.utc).isoformat()
    return summary


async def _analyze_agent(
    session, agent: Agent, today_start: datetime, summary_ref: dict
) -> dict:
    """Compute today's metrics for a single agent."""
    trades_result = await session.execute(
        select(AgentTrade).where(
            AgentTrade.agent_id == agent.id,
            AgentTrade.created_at >= today_start,
        )
    )
    trades = list(trades_result.scalars().all())
    summary_ref["trades_today"] += len(trades)

    wins = [t for t in trades if (t.pnl_dollar or 0) > 0]
    losses = [t for t in trades if (t.pnl_dollar or 0) < 0]
    executed = [t for t in trades if t.decision_status == "accepted"]
    rejected = [t for t in trades if t.decision_status == "rejected"]
    paper = [t for t in trades if t.decision_status == "paper"]

    total_pnl = sum(float(t.pnl_dollar or 0) for t in trades)

    return {
        "agent_id": str(agent.id),
        "agent_name": agent.name,
        "current_mode": agent.current_mode,
        "trades_total": len(trades),
        "trades_executed": len(executed),
        "trades_rejected": len(rejected),
        "trades_paper": len(paper),
        "wins": len(wins),
        "losses": len(losses),
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(len(wins) / len(trades), 3) if trades else 0.0,
    }


async def _enrich_trade_signals(today_start: datetime) -> dict:
    """Enrich today's trade_signals with outcome prices and missed-opportunity flag.

    The trade_signals table may not exist yet (Phase B) — this function is
    safe to call either way.
    """
    result = {"enriched": 0, "missed": 0}

    try:
        from shared.db.models.trade_signal import TradeSignal
    except ImportError:
        logger.info("trade_signals model not available yet — skipping enrichment")
        return result

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance not available — skipping enrichment")
        return result

    async for session in get_session():
        signals_result = await session.execute(
            select(TradeSignal).where(
                TradeSignal.created_at >= today_start,
                TradeSignal.evaluated_at.is_(None),
            )
        )
        signals = list(signals_result.scalars().all())

        # Group tickers to minimize yfinance calls
        tickers = list({s.ticker for s in signals if s.ticker})
        price_cache: dict[str, float] = {}

        for ticker in tickers:
            try:
                data = yf.download(ticker, period="1d", progress=False)
                if not data.empty:
                    if hasattr(data.columns, "levels"):
                        data.columns = data.columns.get_level_values(0)
                    price_cache[ticker] = float(data["Close"].iloc[-1])
            except Exception as exc:
                logger.debug("yfinance failed for %s: %s", ticker, exc)

        now = datetime.now(timezone.utc)
        for sig in signals:
            eod_price = price_cache.get(sig.ticker)
            if eod_price is None:
                continue

            # Approximate entry_price — we don't store it per-signal yet,
            # but we can compare against the features snapshot if present
            features = sig.features or {}
            entry_ref = features.get("entry_price") or features.get("price") or eod_price

            sig.outcome_price_eod = eod_price
            sig.evaluated_at = now

            if entry_ref > 0:
                # Directional P&L
                if sig.direction == "buy":
                    pnl_pct = (eod_price - entry_ref) / entry_ref * 100
                elif sig.direction == "sell":
                    pnl_pct = (entry_ref - eod_price) / entry_ref * 100
                else:
                    pnl_pct = 0.0
                sig.realized_pnl_pct = round(pnl_pct, 4)

                # Flag as missed opportunity: rejected but would have won >2%
                if sig.decision == "rejected" and pnl_pct >= 2.0:
                    sig.was_missed_opportunity = True
                    result["missed"] += 1

            result["enriched"] += 1

        await session.commit()

    return result


def _format_summary_for_notification(summary: dict) -> str:
    """Build the WhatsApp message body."""
    lines = [
        f"EOD Summary — {datetime.now(timezone.utc).strftime('%b %d, %Y')}",
        "",
        f"Agents analyzed: {summary['agents_analyzed']}",
        f"Total trades today: {summary['trades_today']}",
    ]
    if summary.get("signals_enriched"):
        lines.append(f"Signals evaluated: {summary['signals_enriched']}")
    if summary.get("missed_opportunities"):
        lines.append(f"Missed opportunities: {summary['missed_opportunities']}")

    lines.append("")
    lines.append("Per-agent:")
    for a in summary.get("per_agent", [])[:10]:
        pnl_str = f"${a['total_pnl']:+.2f}"
        lines.append(
            f"• {a['agent_name']}: {a['trades_total']} trades "
            f"({a['wins']}W/{a['losses']}L) {pnl_str}"
        )
    if summary.get("errors"):
        lines.append("")
        lines.append(f"Errors: {len(summary['errors'])}")

    return "\n".join(lines)


@router.post("/eod-analysis")
async def trigger_eod_analysis():
    """Spawn the EOD analysis Claude agent.

    As of the Python→Claude migration, the manual trigger ALWAYS spawns the
    first-class Claude Code agent. The scheduler cron at 16:45 ET does the
    same thing via gateway.create_eod_analysis_agent(). Actual output lands
    in briefing_history a few minutes later.
    """
    try:
        from apps.api.src.services.agent_gateway import gateway
        task_key = await gateway.create_eod_analysis_agent()
        return {
            "status": "spawned",
            "task_key": task_key,
            "detail": (
                "EOD analysis agent running. "
                "Results will appear in Briefing History (kind=eod) in 2-3 minutes."
            ),
        }
    except Exception as exc:
        logger.exception("EOD analysis agent spawn failed")
        return {"status": "error", "error": str(exc)[:500]}


@router.get("/eod-analysis/latest")
async def get_latest_eod(session: DbSession):
    """Return the latest EOD notification from the notifications table."""
    try:
        from shared.db.models.notification import Notification
        from sqlalchemy import desc
        result = await session.execute(
            select(Notification)
            .where(Notification.title.like("%EOD%"))
            .order_by(desc(Notification.created_at))
            .limit(1)
        )
        notif = result.scalar_one_or_none()
        if not notif:
            return {"found": False}
        return {
            "found": True,
            "title": notif.title,
            "body": notif.body,
            "created_at": notif.created_at.isoformat() if notif.created_at else None,
            "data": notif.data,
        }
    except Exception as exc:
        return {"found": False, "error": str(exc)[:200]}
