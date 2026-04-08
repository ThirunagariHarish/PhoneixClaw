"""Emit a structured trade signal to the database."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Module-level conditional imports so unit tests can patch create_async_engine
try:
    from sqlalchemy import text as _sa_text  # noqa: F401
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker as _sessionmaker
    from sqlalchemy.pool import NullPool
except ImportError:  # pragma: no cover
    create_async_engine = None  # type: ignore[assignment]
    _sa_text = None  # type: ignore[assignment]
    AsyncSession = None  # type: ignore[assignment]
    _sessionmaker = None  # type: ignore[assignment]
    NullPool = None  # type: ignore[assignment]


async def emit_trade_signal(
    agent_id: str,
    ticker: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    confidence: int,
    reasoning: str,
    analyst_persona: str,
    tool_signals_used: dict,
    pattern_name: str | None = None,
    db_url: str | None = None,
) -> str:
    """Insert a new TradeSignal row into the database.

    Computes decision (executed/watchlist/rejected) based on confidence threshold.
    Computes risk_reward_ratio from entry/stop/target prices.

    Args:
        agent_id: UUID of the analyst agent.
        ticker: Stock ticker symbol.
        direction: 'buy' or 'sell'.
        entry_price: Planned entry price.
        stop_loss: Stop loss price.
        take_profit: Take profit target price.
        confidence: Confidence score 0-100.
        reasoning: Human-readable analysis reasoning.
        analyst_persona: Persona ID string.
        tool_signals_used: Dict of tool outputs used.
        pattern_name: Optional detected pattern name.
        db_url: Database URL. Falls back to DATABASE_URL env var.

    Returns:
        The new signal_id as a UUID string, or empty string on failure.
    """
    url = db_url or os.environ.get("DATABASE_URL", "")
    if not url:
        logger.warning("emit_trade_signal: DATABASE_URL not set — signal not saved")
        return ""  # Indicate failure; caller must not treat as success

    if confidence >= 70:
        decision = "executed"
    elif confidence >= 50:
        decision = "watchlist"
    else:
        decision = "rejected"

    try:
        if direction == "buy":
            risk = entry_price - stop_loss
            reward = take_profit - entry_price
        else:
            risk = stop_loss - entry_price
            reward = entry_price - take_profit
        risk_reward_ratio = round(reward / risk, 2) if risk > 0 else 0.0
    except (ZeroDivisionError, TypeError):
        risk_reward_ratio = 0.0

    signal_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    try:
        if create_async_engine is None:
            logger.warning("emit_trade_signal: sqlalchemy not available — signal not saved")
            return ""

        from sqlalchemy import text
        from sqlalchemy.orm import sessionmaker

        async_url = url.replace("postgresql://", "postgresql+asyncpg://").replace(
            "postgres://", "postgresql+asyncpg://"
        )

        # NullPool: no connection pooling — correct for short-lived subprocess tools
        engine = create_async_engine(async_url, echo=False, pool_pre_ping=True, poolclass=NullPool)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            await session.execute(
                text("""
                    INSERT INTO trade_signals (
                        id, agent_id, ticker, direction, signal_source,
                        decision, rejection_reason, features,
                        analyst_persona, tool_signals_used, risk_reward_ratio,
                        take_profit, entry_price, stop_loss, pattern_name,
                        model_confidence, created_at
                    ) VALUES (
                        :id, :agent_id, :ticker, :direction, 'analyst',
                        :decision, :reasoning, :features,
                        :analyst_persona, :tool_signals_used, :risk_reward_ratio,
                        :take_profit, :entry_price, :stop_loss, :pattern_name,
                        :confidence, :created_at
                    )
                """),
                {
                    "id": str(signal_id),
                    "agent_id": agent_id,
                    "ticker": ticker,
                    "direction": direction,
                    "decision": decision,
                    "reasoning": reasoning,
                    "features": json.dumps(tool_signals_used),
                    "analyst_persona": analyst_persona,
                    "tool_signals_used": json.dumps(tool_signals_used),
                    "risk_reward_ratio": risk_reward_ratio,
                    "take_profit": take_profit,
                    "entry_price": entry_price,
                    "stop_loss": stop_loss,
                    "pattern_name": pattern_name,
                    "confidence": confidence / 100.0,
                    "created_at": now,
                },
            )
            await session.commit()

        await engine.dispose()
        logger.info("emit_trade_signal: saved signal %s for %s (%s, confidence=%d)",
                    signal_id, ticker, direction, confidence)
        return str(signal_id)

    except Exception as exc:
        logger.warning("emit_trade_signal error: %s", exc)
        return ""  # Empty string signals failure to the caller


async def _main_async(args: argparse.Namespace) -> None:
    signal_id = await emit_trade_signal(
        agent_id=args.agent_id,
        ticker=args.ticker,
        direction=args.direction,
        entry_price=args.entry_price,
        stop_loss=args.stop_loss,
        take_profit=args.take_profit,
        confidence=args.confidence,
        reasoning=args.reasoning,
        analyst_persona=args.persona,
        tool_signals_used={},
        db_url=args.db_url,
    )
    print(json.dumps({"signal_id": signal_id}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Emit a trade signal to the database")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--direction", choices=["buy", "sell"], required=True)
    parser.add_argument("--entry-price", type=float, required=True)
    parser.add_argument("--stop-loss", type=float, required=True)
    parser.add_argument("--take-profit", type=float, required=True)
    parser.add_argument("--confidence", type=int, default=50)
    parser.add_argument("--reasoning", default="")
    parser.add_argument("--persona", default="aggressive_momentum")
    parser.add_argument("--db-url", default=None)
    args = parser.parse_args()
    asyncio.run(_main_async(args))
