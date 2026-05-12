"""Feature extraction background worker — computes ~200 features for parsed trades.

Reads from `parsed_trades` table, computes features using enrich_trade, and writes
to `enriched_trades` table. Runs nightly via K8s CronJob.

Idempotent: skips trades already computed for computed_version='v1'.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg

# Add repo root to sys.path
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from services.feature_extraction.src.features import compute_features_for_trade  # noqa: E402

# Constants
BATCH_SIZE = 500
LOG_INTERVAL = 100
COMPUTED_VERSION = "v1"

# Signal handling for graceful shutdown
_shutdown_requested = False


def _signal_handler(signum: int, frame: Any) -> None:
    global _shutdown_requested
    print(f"Received signal {signum} — will commit current batch and exit.", flush=True)
    _shutdown_requested = True


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


async def fetch_unprocessed_trades(conn: asyncpg.Connection) -> list[dict]:
    """Fetch all trades from parsed_trades that are NOT yet in enriched_trades for v1."""
    query = """
        SELECT pt.id, pt.ticker, pt.side, pt.entry_price, pt.entry_time,
               pt.target_price, pt.stop_loss, pt.channel_id, pt.author_name,
               pt.raw_message, pt.content, pt.exit_price, pt.exit_time, pt.pnl
        FROM parsed_trades pt
        WHERE NOT EXISTS (
            SELECT 1 FROM enriched_trades et
            WHERE et.parsed_trade_id = pt.id
              AND et.computed_version = $1
        )
        ORDER BY pt.entry_time ASC
    """
    rows = await conn.fetch(query, COMPUTED_VERSION)
    return [dict(row) for row in rows]


async def bulk_insert_features(conn: asyncpg.Connection, batch: list[dict]) -> None:
    """Bulk insert enriched features using COPY for speed."""
    if not batch:
        return

    # Prepare records for copy_records_to_table
    records = [
        (
            row["parsed_trade_id"],
            row["ticker"],
            row["entry_time"],
            json.dumps(row["features"]),
            row["computed_at"],
            row["computed_version"],
        )
        for row in batch
    ]

    await conn.copy_records_to_table(
        "enriched_trades",
        columns=["parsed_trade_id", "ticker", "entry_time", "features", "computed_at", "computed_version"],
        records=records,
    )


async def process_batch(trades: list[dict], cache: dict) -> list[dict]:
    """Compute features for a batch of trades."""
    results = []
    now = datetime.now(timezone.utc)

    for trade in trades:
        try:
            features = compute_features_for_trade(trade, cache)
            results.append({
                "parsed_trade_id": trade["id"],
                "ticker": trade["ticker"],
                "entry_time": trade["entry_time"],
                "features": features,
                "computed_at": now,
                "computed_version": COMPUTED_VERSION,
            })
        except Exception as e:
            print(f"  ERROR computing features for trade {trade['id']} ({trade['ticker']}): {e}", flush=True)
            # Skip failed trades — don't halt the entire batch
            continue

    return results


@asynccontextmanager
async def get_db_connection():
    """Get async DB connection from DATABASE_URL."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL environment variable is required")

    # asyncpg requires asyncpg-style DSN (postgresql:// or postgres://)
    conn = await asyncpg.connect(db_url)
    try:
        yield conn
    finally:
        await conn.close()


async def main_async() -> None:
    """Main entry point for feature extraction worker."""
    print(f"Feature extraction worker starting at {datetime.now(timezone.utc).isoformat()}", flush=True)
    print(f"  COMPUTED_VERSION: {COMPUTED_VERSION}", flush=True)
    print(f"  BATCH_SIZE: {BATCH_SIZE}", flush=True)

    # Check for PHOENIX_PRICE_CACHE_DIR
    price_cache_dir = os.environ.get("PHOENIX_PRICE_CACHE_DIR")
    if price_cache_dir:
        print(f"  PHOENIX_PRICE_CACHE_DIR: {price_cache_dir}", flush=True)
        # enrich.py reads this env var internally for disk cache
    else:
        print("  PHOENIX_PRICE_CACHE_DIR not set — downloads will not be cached", flush=True)

    async with get_db_connection() as conn:
        # Fetch all unprocessed trades
        trades = await fetch_unprocessed_trades(conn)
        total_count = len(trades)
        print(f"Found {total_count} trades to process", flush=True)

        if total_count == 0:
            print("No work to do — exiting.", flush=True)
            return

        # Shared cache for yfinance data, sentiment classifier, etc.
        cache: dict = {}

        processed_count = 0
        batch_num = 0

        # Process in batches
        for i in range(0, total_count, BATCH_SIZE):
            if _shutdown_requested:
                print(f"Shutdown requested — processed {processed_count}/{total_count} trades", flush=True)
                break

            batch = trades[i:i + BATCH_SIZE]
            batch_num += 1

            print(f"Processing batch {batch_num} ({len(batch)} trades)...", flush=True)

            # Compute features (CPU-bound — runs in the event loop)
            results = await process_batch(batch, cache)

            # Bulk insert
            await bulk_insert_features(conn, results)

            processed_count += len(results)

            # Log progress
            if processed_count % LOG_INTERVAL == 0 or (i + BATCH_SIZE) >= total_count:
                print(f"  Progress: {processed_count}/{total_count} trades ({processed_count * 100 // total_count}%)", flush=True)

    print(f"Feature extraction complete: {processed_count}/{total_count} trades processed", flush=True)
    print(f"Finished at {datetime.now(timezone.utc).isoformat()}", flush=True)


def main() -> None:
    """Synchronous entry point."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("Interrupted by user", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"FATAL ERROR: {e}", flush=True, file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
