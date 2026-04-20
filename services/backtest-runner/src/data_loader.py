"""
Market data loader — fetches OHLCV bars from TimescaleDB
with a synthetic-data fallback for testing.

M2.7: Backtest data pipeline.
"""
from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TIMESCALE_DSN = os.getenv("TIMESCALE_DSN", "")


def _load_from_timescale(
    symbol: str, timeframe: str, start: str, end: str
) -> pd.DataFrame | None:
    """Attempt to load bars from TimescaleDB. Returns None on failure."""
    if not TIMESCALE_DSN:
        return None

    try:
        import psycopg2
        conn = psycopg2.connect(TIMESCALE_DSN)
        query = """
            SELECT time, open, high, low, close, volume
            FROM ohlcv_bars
            WHERE symbol = %s AND timeframe = %s
              AND time >= %s AND time <= %s
            ORDER BY time
        """
        df = pd.read_sql(query, conn, params=(symbol, timeframe, start, end))
        conn.close()
        if not df.empty:
            logger.info("Loaded %d bars for %s from TimescaleDB", len(df), symbol)
            return df
    except Exception:
        logger.warning("TimescaleDB unavailable, falling back to synthetic data")

    return None


def _generate_synthetic(
    symbol: str, timeframe: str, start: str, end: str
) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    freq_map = {
        "1m": "1min", "5m": "5min", "15m": "15min",
        "1h": "1h", "4h": "4h", "1d": "1D",
    }
    freq = freq_map.get(timeframe, "1D")
    times = pd.date_range(start=start, end=end, freq=freq)

    rng = np.random.default_rng(hash(symbol) & 0xFFFFFFFF)
    price = 100.0
    rows = []
    for t in times:
        change = rng.normal(0, 0.02)
        o = price
        c = price * (1 + change)
        h = max(o, c) * (1 + abs(rng.normal(0, 0.005)))
        l = min(o, c) * (1 - abs(rng.normal(0, 0.005)))  # noqa: E741
        v = int(rng.integers(1000, 100000))
        rows.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v})
        price = c

    logger.info("Generated %d synthetic bars for %s (%s)", len(rows), symbol, timeframe)
    return pd.DataFrame(rows)


def load_bars(
    symbol: str,
    timeframe: str = "1d",
    start: str = "2024-01-01",
    end: str = "2024-12-31",
) -> pd.DataFrame:
    """Load OHLCV bars — tries TimescaleDB first, then synthetic fallback.

    Returns a DataFrame with columns: time, open, high, low, close, volume.
    """
    df = _load_from_timescale(symbol, timeframe, start, end)
    if df is not None:
        return df
    return _generate_synthetic(symbol, timeframe, start, end)
