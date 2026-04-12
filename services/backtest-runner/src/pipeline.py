"""
Backtest pipeline orchestrator — wires together message ingestion, signal parsing,
trade reconstruction, market enrichment, and pattern analysis.

Replaces the mock backtest-complete endpoint with a real analysis pipeline.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.agent import Agent, AgentBacktest
from shared.db.models.backtest_trade import BacktestTrade
from shared.db.models.channel_message import ChannelMessage
from shared.db.models.connector import Connector, ConnectorAgent

from .market_enricher import enrich_trades
from .pattern_engine import analyze_patterns
from .trade_reconstructor import reconstruct_trades

logger = logging.getLogger(__name__)


async def run_backtest_pipeline(
    session: AsyncSession,
    agent_id: uuid.UUID,
    backtest_id: uuid.UUID,
    progress_callback=None,
) -> dict:
    """
    Full backtest pipeline:
    1. Find agent's connected channels
    2. Ingest historical messages (if not already done)
    3. Parse signals and reconstruct trades
    4. Enrich with market data
    5. Run pattern analysis
    6. Update backtest record with real metrics
    """

    # ── Step 0: Dispatch to trend pipeline if applicable ────────────────
    agent = await session.get(Agent, agent_id)
    if not agent:
        return {"error": "Agent not found"}

    if agent.type == "trend":
        from .trend_pipeline import run_trend_backtest
        return await run_trend_backtest(session, agent_id, backtest_id, progress_callback)

    # ── Step 1: Resolve connectors ───────────────────────────────────────

    links = (await session.execute(
        select(ConnectorAgent).where(ConnectorAgent.agent_id == agent_id)
    )).scalars().all()

    if not links:
        return {"error": "No connectors linked to agent"}

    if progress_callback:
        await progress_callback("resolving_connectors", 5)

    all_trades: list[BacktestTrade] = []
    valid_connector_count = 0
    empty_connector_count = 0

    for link in links:
        connector = await session.get(Connector, link.connector_id)
        if not connector:
            continue

        valid_connector_count += 1

        # ── Step 2: Check for existing messages or ingest ────────────
        msg_count = (await session.execute(
            select(func.count(ChannelMessage.id)).where(
                ChannelMessage.connector_id == connector.id
            )
        )).scalar() or 0

        if msg_count == 0:
            if progress_callback:
                await progress_callback("ingesting_messages", 10)

            try:
                from shared.crypto.credentials import decrypt_credentials
                creds = decrypt_credentials(connector.credentials_encrypted) if connector.credentials_encrypted else {}
            except Exception:
                creds = {}

            try:
                from services.message_ingestion.src.orchestrator import ingest_history
                await ingest_history(
                    session=session,
                    connector_id=connector.id,
                    connector_type=connector.type,
                    credentials=creds,
                    config=connector.config or {},
                )
            except Exception as e:
                logger.error("Message ingestion failed for connector %s: %s", connector.id, e)

            # Re-check after ingestion attempt
            msg_count = (await session.execute(
                select(func.count(ChannelMessage.id)).where(
                    ChannelMessage.connector_id == connector.id
                )
            )).scalar() or 0

            if msg_count == 0:
                logger.warning(
                    "No messages for connector %s (channel: %s) — skipping this connector.",
                    connector.id, link.channel,
                )
                empty_connector_count += 1
                continue  # skip this connector; try remaining ones

        # ── Step 3: Reconstruct trades ───────────────────────────────
        if progress_callback:
            await progress_callback("parsing_signals", 30)

        channel_filter = link.channel if link.channel != "*" else None
        config = agent.config or {}
        if not channel_filter and "selected_channel" in config:
            ch = config["selected_channel"]
            channel_filter = ch.get("channel_name") if isinstance(ch, dict) else None

        trades = await reconstruct_trades(
            session=session,
            backtest_id=backtest_id,
            agent_id=agent_id,
            connector_id=connector.id,
            channel_filter=channel_filter,
        )
        all_trades.extend(trades)

    # ── Post-loop: guard — no resolvable connectors at all ────────────────
    if valid_connector_count == 0:
        logger.warning(
            "Agent %s has %d connector link(s) but none resolved to a valid Connector record — aborting backtest.",
            agent_id, len(links),
        )
        backtest = await session.get(AgentBacktest, backtest_id)
        if backtest:
            backtest.status = "FAILED"
            backtest.error_message = (
                "No valid connectors found for this agent. "
                "Please re-link your Discord channel and try again."
            )
            backtest.completed_at = datetime.now(timezone.utc)
        if agent:
            agent.status = "CREATED"
        await session.commit()
        return {"error": "no_valid_connectors", "message": "No valid connectors found."}

    # ── Post-loop: fail cleanly when every valid connector had no messages ──
    if valid_connector_count > 0 and empty_connector_count == valid_connector_count:
        logger.warning(
            "All %d connector(s) for agent %s had no messages after ingestion — aborting backtest.",
            valid_connector_count, agent_id,
        )
        if progress_callback:
            await progress_callback("no_messages", 0)
        backtest = await session.get(AgentBacktest, backtest_id)
        if backtest:
            backtest.status = "FAILED"
            backtest.error_message = (
                "No messages found in any connected Discord channel. "
                "Backtesting requires historical messages to analyse. "
                "Please ensure the channel has activity and try again."
            )
            backtest.completed_at = datetime.now(timezone.utc)
        if agent:
            agent.status = "CREATED"
        await session.commit()
        return {
            "error": "no_messages",
            "message": (
                "No messages found in the connected Discord channel(s). "
                "Backtesting skipped."
            ),
        }

    # ── Step 4: Market data enrichment ───────────────────────────────────
    if progress_callback:
        await progress_callback("enriching_market_data", 60)

    if all_trades:
        all_trades = await enrich_trades(all_trades)

    # ── Step 5: Pattern analysis ─────────────────────────────────────────
    if progress_callback:
        await progress_callback("analyzing_patterns", 80)

    intelligence = analyze_patterns(all_trades)

    # Count total messages analyzed
    total_messages = (await session.execute(
        select(func.count(ChannelMessage.id)).where(
            ChannelMessage.connector_id.in_([l.connector_id for l in links])
        )
    )).scalar() or 0
    intelligence["overall_channel_metrics"]["total_messages_analyzed"] = total_messages

    # ── Step 6: Compute summary metrics and update backtest ──────────────
    if progress_callback:
        await progress_callback("computing_metrics", 90)

    total_count = len(all_trades)
    profitable_count = sum(1 for t in all_trades if t.is_profitable)
    win_rate = profitable_count / total_count if total_count > 0 else 0

    pnls = [t.pnl_pct for t in all_trades]
    total_return = sum(pnls)

    # Sharpe ratio (simplified: daily returns approximation)
    if len(pnls) > 1:
        avg_ret = total_return / len(pnls)
        std_ret = (sum((r - avg_ret) ** 2 for r in pnls) / len(pnls)) ** 0.5
        sharpe = (avg_ret / std_ret * (252 ** 0.5)) if std_ret > 0 else 0
    else:
        sharpe = 0

    # Max drawdown from cumulative PnL
    cumulative = []
    running = 0
    for p in pnls:
        running += p
        cumulative.append(running)
    peak = 0
    max_dd = 0
    for val in cumulative:
        peak = max(peak, val)
        dd = peak - val
        max_dd = max(max_dd, dd)

    # Equity curve
    equity_curve = []
    eq = 100000
    for i, p in enumerate(pnls):
        eq *= (1 + p / 100)
        equity_curve.append({"day": i, "equity": round(eq, 2)})

    # Update backtest record
    backtest = await session.get(AgentBacktest, backtest_id)
    if backtest:
        backtest.status = "COMPLETED"
        backtest.total_trades = total_count
        backtest.win_rate = round(win_rate, 4)
        backtest.total_return = round(total_return, 2)
        backtest.sharpe_ratio = round(sharpe, 2)
        backtest.max_drawdown = round(max_dd, 2)
        backtest.equity_curve = equity_curve
        backtest.metrics = intelligence
        backtest.completed_at = datetime.now(timezone.utc)

    # Update agent status
    if agent:
        agent.status = "BACKTEST_COMPLETE"

    await session.commit()

    if progress_callback:
        await progress_callback("complete", 100)

    logger.info(
        "Backtest pipeline complete for agent %s: %d trades, %.1f%% win rate, %.2f%% return",
        agent_id, total_count, win_rate * 100, total_return,
    )

    return {
        "total_trades": total_count,
        "win_rate": win_rate,
        "total_return": total_return,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "rules_discovered": len(intelligence.get("rules", [])),
    }
