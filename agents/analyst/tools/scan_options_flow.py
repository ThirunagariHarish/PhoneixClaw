"""Scan options flow signals from trade_signals table."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


async def scan_options_flow(
    ticker: str,
    since_minutes: int = 60,
    db_url: str | None = None,
) -> dict:
    """Query trade_signals for options flow data for a given ticker.

    Parses unusual_whales signals to extract put/call ratios, sweep counts,
    and dominant side.

    Args:
        ticker: Stock ticker symbol.
        since_minutes: How far back to look.
        db_url: Database URL. Falls back to DATABASE_URL env var.

    Returns:
        Dict with sweep_count, put_call_ratio, unusual_activity, etc.
    """
    url = db_url or os.environ.get("DATABASE_URL", "")
    default_result = {
        "sweep_count": 0,
        "call_count": 0,
        "put_count": 0,
        "put_call_ratio": 1.0,
        "unusual_activity": False,
        "dominant_side": "neutral",
        "iv_signal": "normal",
        "signal": "neutral",
    }

    if not url:
        logger.warning("scan_options_flow: DATABASE_URL not set — returning neutral")
        return default_result

    try:
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import NullPool

        async_url = url.replace("postgresql://", "postgresql+asyncpg://").replace(
            "postgres://", "postgresql+asyncpg://"
        )

        # NullPool: no connection pooling — correct for short-lived subprocess tools
        engine = create_async_engine(async_url, echo=False, pool_pre_ping=True, poolclass=NullPool)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

        async with async_session() as session:
            result = await session.execute(
                text("""
                    SELECT features
                    FROM trade_signals
                    WHERE ticker = :ticker
                      AND signal_source = 'unusual_whales'
                      AND created_at >= :cutoff
                    ORDER BY created_at DESC
                    LIMIT 100
                """),
                {"ticker": ticker, "cutoff": cutoff},
            )
            rows = result.fetchall()

        await engine.dispose()

        call_count = 0
        put_count = 0
        sweep_count = 0
        iv_values: list[float] = []

        for (features,) in rows:
            if not isinstance(features, dict):
                continue

            contract_type = str(features.get("contract_type", features.get("type", ""))).lower()
            if "call" in contract_type:
                call_count += 1
            elif "put" in contract_type:
                put_count += 1

            order_type = str(features.get("order_type", features.get("trade_type", ""))).lower()
            if "sweep" in order_type:
                sweep_count += 1

            iv = features.get("iv", features.get("implied_volatility", None))
            if iv is not None:
                try:
                    iv_values.append(float(iv))
                except (TypeError, ValueError):
                    pass

        put_call_ratio = (put_count / call_count) if call_count > 0 else 1.0
        unusual_activity = sweep_count >= 3 or (call_count + put_count) >= 10

        if call_count > put_count * 1.5:
            dominant_side = "calls"
        elif put_count > call_count * 1.5:
            dominant_side = "puts"
        else:
            dominant_side = "neutral"

        avg_iv = sum(iv_values) / len(iv_values) if iv_values else 0.0
        if avg_iv > 0.5:
            iv_signal = "high"
        elif avg_iv > 0.2:
            iv_signal = "normal"
        else:
            iv_signal = "low"

        if dominant_side == "calls" and unusual_activity:
            signal = "bullish"
        elif dominant_side == "puts" and unusual_activity:
            signal = "bearish"
        elif dominant_side == "calls":
            signal = "bullish"
        elif dominant_side == "puts":
            signal = "bearish"
        else:
            signal = "neutral"

        return {
            "sweep_count": sweep_count,
            "call_count": call_count,
            "put_count": put_count,
            "put_call_ratio": round(put_call_ratio, 2),
            "unusual_activity": unusual_activity,
            "dominant_side": dominant_side,
            "iv_signal": iv_signal,
            "signal": signal,
        }

    except Exception as exc:
        logger.warning("scan_options_flow error for %s: %s", ticker, exc)
        return {**default_result, "error": str(exc)}


async def _main_async(args: argparse.Namespace) -> None:
    result = await scan_options_flow(args.ticker, args.since_minutes, args.db_url)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scan options flow for a ticker")
    parser.add_argument("ticker", help="Stock ticker symbol (e.g. AAPL)")
    parser.add_argument("--since-minutes", type=int, default=60)
    parser.add_argument("--db-url", default=None)
    args = parser.parse_args()
    asyncio.run(_main_async(args))
