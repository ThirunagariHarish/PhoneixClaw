#!/usr/bin/env python3
"""Backfill daily OHLC bars into Postgres for Phoenix Trade Bot.

Usage:
    python scripts/backfill_daily_bars.py --years 5 --batch-size 50
    python scripts/backfill_daily_bars.py --years 3 --max-concurrent 8
    python scripts/backfill_daily_bars.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, timedelta

import asyncpg
import pandas as pd

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Hard-coded context tickers (market indices and sector ETFs)
CONTEXT_TICKERS = [
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "^VIX",
    "TLT",
    "GLD",
    "XLF",
    "XLK",
    "XLE",
    "XLV",
    "XLI",
    "XLC",
    "XLU",
    "XLP",
    "XLB",
    "XLRE",
]


def get_database_url() -> str:
    """Get DATABASE_URL from environment, strip +asyncpg dialect if present."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL environment variable not set")
        sys.exit(1)

    # asyncpg requires postgresql:// not postgresql+asyncpg://
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    return db_url


async def get_tickers_from_parsed_trades(conn: asyncpg.Connection) -> list[str]:
    """Fetch distinct tickers from parsed_trades table.

    Returns empty list if table doesn't exist (graceful degradation).
    """
    try:
        # Check if parsed_trades table exists
        exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'parsed_trades'
            )
            """
        )

        if not exists:
            logger.warning("parsed_trades table does not exist, skipping trade ticker extraction")
            return []

        # Fetch distinct tickers
        rows = await conn.fetch("SELECT DISTINCT ticker FROM parsed_trades WHERE ticker IS NOT NULL")
        tickers = [row["ticker"] for row in rows]
        logger.info("Found %d distinct tickers in parsed_trades", len(tickers))
        return tickers

    except Exception as exc:
        logger.warning("Failed to query parsed_trades: %s — continuing with context tickers only", exc)
        return []


def build_ticker_list(parsed_tickers: list[str]) -> list[str]:
    """Build deduplicated list of tickers: parsed_trades + context tickers."""
    all_tickers = list(set(parsed_tickers + CONTEXT_TICKERS))
    all_tickers.sort()
    logger.info("Total unique tickers to backfill: %d", len(all_tickers))
    return all_tickers


async def get_latest_date_for_ticker(conn: asyncpg.Connection, ticker: str) -> date | None:
    """Get the latest date we have in daily_bars for this ticker."""
    row = await conn.fetchrow(
        "SELECT MAX(date) as latest FROM daily_bars WHERE ticker = $1",
        ticker,
    )
    return row["latest"] if row and row["latest"] else None


async def fetch_daily_bars_yfinance(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Fetch daily bars using yfinance.

    Returns DataFrame with columns: [open, high, low, close, adj_close, volume]
    indexed by date. Returns empty DataFrame if no data.
    """
    try:
        import yfinance as yf

        # Run yfinance download in executor to avoid blocking event loop
        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None,
            lambda: yf.download(
                ticker,
                start=start,
                end=end,
                progress=False,
                auto_adjust=False,
            ),
        )

        if df.empty:
            return pd.DataFrame()

        # Normalize column names to lowercase
        df.columns = [col.lower() if isinstance(col, str) else col for col in df.columns]

        # Handle multi-level columns from yfinance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Ensure we have required columns
        required = ["open", "high", "low", "close", "volume"]
        if not all(col in df.columns for col in required):
            logger.warning("Missing required columns for %s: %s", ticker, df.columns.tolist())
            return pd.DataFrame()

        # Add adj_close if not present (use close as fallback)
        if "adj_close" not in df.columns and "adj close" not in df.columns:
            df["adj_close"] = df["close"]
        elif "adj close" in df.columns:
            df["adj_close"] = df["adj close"]
            df = df.drop(columns=["adj close"])

        # Select only needed columns
        df = df[["open", "high", "low", "close", "adj_close", "volume"]]

        # Ensure date index
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        # Remove timezone info for consistency with date column in DB
        df.index = df.index.tz_localize(None)

        return df

    except Exception as exc:
        logger.error("Failed to fetch data for %s: %s", ticker, exc)
        return pd.DataFrame()


async def upsert_daily_bars(
    conn: asyncpg.Connection,
    ticker: str,
    df: pd.DataFrame,
    source: str = "yfinance",
) -> int:
    """Bulk upsert daily bars into daily_bars table.

    Returns number of rows inserted/updated.
    """
    if df.empty:
        return 0

    # Prepare records for copy
    records = []
    for dt, row in df.iterrows():
        records.append(
            (
                ticker,
                dt.date(),  # Convert datetime to date
                float(row["open"]) if pd.notna(row["open"]) else None,
                float(row["high"]) if pd.notna(row["high"]) else None,
                float(row["low"]) if pd.notna(row["low"]) else None,
                float(row["close"]) if pd.notna(row["close"]) else None,
                float(row["adj_close"]) if pd.notna(row["adj_close"]) else None,
                int(row["volume"]) if pd.notna(row["volume"]) else None,
                source,
            )
        )

    if not records:
        return 0

    # Create temp table
    temp_table = f"temp_daily_bars_{ticker.replace('^', '').replace('=', '')}"[:63]
    await conn.execute(
        f"""
        CREATE TEMP TABLE {temp_table} (
            ticker VARCHAR(20),
            date DATE,
            open NUMERIC(20, 6),
            high NUMERIC(20, 6),
            low NUMERIC(20, 6),
            close NUMERIC(20, 6),
            adj_close NUMERIC(20, 6),
            volume BIGINT,
            source VARCHAR(20)
        )
        """
    )

    # Bulk insert into temp table
    await conn.copy_records_to_table(
        temp_table,
        records=records,
        columns=["ticker", "date", "open", "high", "low", "close", "adj_close", "volume", "source"],
    )

    # Upsert from temp to daily_bars
    result = await conn.fetch(
        f"""
        INSERT INTO daily_bars (ticker, date, open, high, low, close, adj_close, volume, source, ingested_at)
        SELECT ticker, date, open, high, low, close, adj_close, volume, source, NOW()
        FROM {temp_table}
        ON CONFLICT (ticker, date)
        DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            adj_close = EXCLUDED.adj_close,
            volume = EXCLUDED.volume,
            source = EXCLUDED.source,
            ingested_at = NOW()
        RETURNING ticker, date
        """
    )

    # Drop temp table
    await conn.execute(f"DROP TABLE {temp_table}")

    return len(result)


async def backfill_ticker(
    conn: asyncpg.Connection,
    ticker: str,
    years: int,
    dry_run: bool = False,
) -> tuple[str, int]:
    """Backfill a single ticker.

    Returns (ticker, rows_inserted).
    """
    try:
        # Get latest date we have
        latest_date = await get_latest_date_for_ticker(conn, ticker)
        today = date.today()

        if latest_date:
            # Check if already up-to-date
            if latest_date >= today - timedelta(days=1):
                logger.debug("%s already up-to-date (latest: %s)", ticker, latest_date)
                return (ticker, 0)
            # Start from day after latest
            start_date = latest_date + timedelta(days=1)
        else:
            # No existing data, start from N years ago
            start_date = today - timedelta(days=years * 365)

        # Fetch data
        logger.debug("Fetching %s from %s to %s", ticker, start_date, today)
        df = await fetch_daily_bars_yfinance(ticker, start_date, today)

        if df.empty:
            logger.debug("%s: no data returned", ticker)
            return (ticker, 0)

        if dry_run:
            logger.info("[DRY-RUN] Would insert %d rows for %s", len(df), ticker)
            return (ticker, len(df))

        # Upsert to database
        rows_inserted = await upsert_daily_bars(conn, ticker, df)
        logger.debug("%s: inserted/updated %d rows", ticker, rows_inserted)
        return (ticker, rows_inserted)

    except Exception as exc:
        logger.error("Error backfilling %s: %s", ticker, exc)
        return (ticker, 0)


async def backfill_with_concurrency(
    conn: asyncpg.Connection,
    tickers: list[str],
    years: int,
    max_concurrent: int,
    dry_run: bool = False,
) -> dict[str, int]:
    """Backfill all tickers with controlled concurrency.

    Returns dict of {ticker: rows_inserted}.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results: dict[str, int] = {}
    total_tickers = len(tickers)
    completed = 0

    async def backfill_with_semaphore(ticker: str) -> tuple[str, int]:
        async with semaphore:
            return await backfill_ticker(conn, ticker, years, dry_run)

    # Process all tickers
    tasks = [backfill_with_semaphore(ticker) for ticker in tickers]

    # Report progress every 10 tickers
    for coro in asyncio.as_completed(tasks):
        ticker, rows = await coro
        results[ticker] = rows
        completed += 1

        if completed % 10 == 0 or completed == total_tickers:
            total_rows = sum(results.values())
            logger.info(
                "Progress: %d/%d tickers completed, %d total rows",
                completed,
                total_tickers,
                total_rows,
            )

    return results


async def main_async(args: argparse.Namespace) -> int:
    """Main async entry point."""
    db_url = get_database_url()

    logger.info("Connecting to database...")
    conn = await asyncpg.connect(db_url)

    try:
        # Build ticker list
        logger.info("Building ticker list...")
        parsed_tickers = await get_tickers_from_parsed_trades(conn)
        tickers = build_ticker_list(parsed_tickers)

        if not tickers:
            logger.error("No tickers to backfill")
            return 1

        logger.info(
            "Starting backfill: %d tickers, %d years history, max %d concurrent",
            len(tickers),
            args.years,
            args.max_concurrent,
        )

        if args.dry_run:
            logger.info("[DRY-RUN MODE] No data will be written")

        # Backfill with concurrency control
        results = await backfill_with_concurrency(
            conn,
            tickers,
            args.years,
            args.max_concurrent,
            args.dry_run,
        )

        # Summary
        total_rows = sum(results.values())
        tickers_with_data = sum(1 for rows in results.values() if rows > 0)
        logger.info(
            "Backfill complete: %d/%d tickers had new data, %d total rows %s",
            tickers_with_data,
            len(tickers),
            total_rows,
            "(would be) inserted" if args.dry_run else "inserted/updated",
        )

        return 0

    except Exception as exc:
        logger.exception("Backfill failed: %s", exc)
        return 1

    finally:
        await conn.close()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill daily OHLC bars into Postgres",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--years",
        type=int,
        default=5,
        help="Number of years of history to backfill for new tickers",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Rows per copy_records_to_table chunk (currently unused, kept for compatibility)",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=4,
        help="Maximum concurrent ticker fetches (avoid rate limits)",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="yfinance",
        help="Market data provider (currently only yfinance supported)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing to database",
    )

    args = parser.parse_args()

    if args.provider != "yfinance":
        logger.warning("Only yfinance provider is currently supported, ignoring --provider flag")

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
