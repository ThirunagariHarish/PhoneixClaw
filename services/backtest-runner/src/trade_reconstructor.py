"""
Trade reconstructor — takes parsed channel messages and reconstructs actual trades.
Pairs buy/sell signals chronologically to compute entry/exit/P&L for each trade.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.channel_message import ChannelMessage
from shared.db.models.backtest_trade import BacktestTrade
from shared.nlp.signal_parser import parse_signal, pair_trades, MessageSignal

logger = logging.getLogger(__name__)


async def reconstruct_trades(
    session: AsyncSession,
    backtest_id: uuid.UUID,
    agent_id: uuid.UUID,
    connector_id: uuid.UUID,
    channel_filter: Optional[str] = None,
) -> list[BacktestTrade]:
    """
    Load all channel messages for a connector, parse signals,
    pair them into trades, and create BacktestTrade rows.
    """
    query = (
        select(ChannelMessage)
        .where(ChannelMessage.connector_id == connector_id)
        .order_by(ChannelMessage.posted_at.asc())
    )
    if channel_filter and channel_filter != "*":
        query = query.where(ChannelMessage.channel == channel_filter)

    result = await session.execute(query)
    messages = result.scalars().all()

    if not messages:
        logger.warning("No messages found for connector %s", connector_id)
        return []

    # Parse each message into signals
    parsed_signals: list[MessageSignal] = []
    for msg in messages:
        parsed = parse_signal(msg.content)

        # Update message_type in DB
        msg.message_type = parsed.signal_type
        msg.tickers_mentioned = parsed.tickers

        if parsed.signal_type in ("buy_signal", "sell_signal", "close_signal"):
            parsed_signals.append(MessageSignal(
                message_id=str(msg.id),
                author=msg.author,
                content=msg.content,
                posted_at=msg.posted_at,
                parsed=parsed,
            ))

    logger.info(
        "Parsed %d messages, found %d actionable signals from connector %s",
        len(messages), len(parsed_signals), connector_id
    )

    # Pair signals into trades
    trade_pairs = pair_trades(parsed_signals)

    # Create BacktestTrade rows
    db_trades: list[BacktestTrade] = []
    for pair in trade_pairs:
        entry_price = pair.entry_signal.parsed.price or 0.0
        exit_price = pair.exit_signal.parsed.price if pair.exit_signal and pair.exit_signal.parsed.price else entry_price
        exit_time = pair.exit_signal.posted_at if pair.exit_signal else pair.entry_signal.posted_at

        pnl = exit_price - entry_price if pair.side == "long" else entry_price - exit_price
        pnl_pct = (pnl / entry_price * 100) if entry_price > 0 else 0.0
        holding_hours = (exit_time - pair.entry_signal.posted_at).total_seconds() / 3600

        trade = BacktestTrade(
            id=uuid.uuid4(),
            backtest_id=backtest_id,
            agent_id=agent_id,
            ticker=pair.ticker,
            side=pair.side,
            entry_price=entry_price,
            exit_price=exit_price,
            entry_time=pair.entry_signal.posted_at,
            exit_time=exit_time,
            pnl=pnl,
            pnl_pct=pnl_pct,
            holding_period_hours=holding_hours,
            signal_message_id=uuid.UUID(pair.entry_signal.message_id),
            close_message_id=uuid.UUID(pair.exit_signal.message_id) if pair.exit_signal else None,
            is_profitable=pnl > 0,
            hour_of_day=pair.entry_signal.posted_at.hour,
            day_of_week=pair.entry_signal.posted_at.weekday(),
            is_pre_market=pair.entry_signal.posted_at.hour < 9 or (
                pair.entry_signal.posted_at.hour == 9 and pair.entry_signal.posted_at.minute < 30
            ),
            pattern_tags=[],
        )
        session.add(trade)
        db_trades.append(trade)

    await session.flush()
    logger.info("Reconstructed %d trades for backtest %s", len(db_trades), backtest_id)
    return db_trades
