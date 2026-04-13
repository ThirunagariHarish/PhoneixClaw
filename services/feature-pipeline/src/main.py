"""Phoenix Feature Pipeline — computes and caches ML features.

Runs two independent sub-pipelines:
1. Market Data Pipeline: OHLC + technical indicators every 60s for watched tickers
2. Sentiment Pipeline: NLP features on new Discord messages (via Redis subscription)
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import redis.asyncio as aioredis
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shared.feature_store.client import FeatureStoreClient

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
MARKET_POLL_INTERVAL = int(os.environ.get("MARKET_POLL_INTERVAL", "60"))

_engine = create_async_engine(DATABASE_URL, pool_size=5, max_overflow=5)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)
_redis: aioredis.Redis | None = None
_bg_tasks: list[asyncio.Task] = []


def _get_watched_tickers() -> list[str]:
    """Return tickers to compute features for.

    Reads from WATCHED_TICKERS env var (comma-separated) or defaults to
    common benchmark tickers. In production, this queries the agents table
    for tickers referenced in active agents' configurations.
    """
    env_tickers = os.environ.get("WATCHED_TICKERS", "")
    if env_tickers:
        return [t.strip().upper() for t in env_tickers.split(",") if t.strip()]
    return ["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "PLTR", "AMZN", "META", "MSFT", "IWM"]


def _compute_technical_indicators(ohlcv: dict[str, Any]) -> dict[str, Any]:
    """Compute technical indicators from OHLCV data.

    Uses pandas/numpy for computation. Returns a flat dict of indicator values.
    """
    try:
        import numpy as np
        import pandas as pd
    except ImportError:
        log.warning("numpy/pandas not available, returning empty technicals")
        return {}

    close_prices = ohlcv.get("close_history", [])
    high_prices = ohlcv.get("high_history", [])
    low_prices = ohlcv.get("low_history", [])
    volume_history = ohlcv.get("volume_history", [])

    if len(close_prices) < 20:
        return {}

    close = pd.Series(close_prices, dtype=float)
    high = pd.Series(high_prices, dtype=float) if high_prices else close
    low = pd.Series(low_prices, dtype=float) if low_prices else close
    vol = pd.Series(volume_history, dtype=float) if volume_history else pd.Series([0] * len(close))

    indicators: dict[str, Any] = {}

    for period in [5, 9, 14, 20, 50, 200]:
        if len(close) >= period:
            indicators[f"sma_{period}"] = round(float(close.rolling(period).mean().iloc[-1]), 4)
            indicators[f"ema_{period}"] = round(float(close.ewm(span=period, adjust=False).mean().iloc[-1]), 4)

    for period in [7, 14, 21]:
        if len(close) >= period + 1:
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0).rolling(period).mean()
            loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))
            indicators[f"rsi_{period}"] = round(float(rsi.iloc[-1]), 2) if not np.isnan(rsi.iloc[-1]) else 50.0

    if len(close) >= 26:
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        indicators["macd"] = round(float(macd_line.iloc[-1]), 4)
        indicators["macd_signal"] = round(float(signal_line.iloc[-1]), 4)
        indicators["macd_histogram"] = round(float((macd_line - signal_line).iloc[-1]), 4)

    if len(close) >= 20:
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        indicators["bb_upper"] = round(float((sma20 + 2 * std20).iloc[-1]), 4)
        indicators["bb_lower"] = round(float((sma20 - 2 * std20).iloc[-1]), 4)
        indicators["bb_middle"] = round(float(sma20.iloc[-1]), 4)
        bb_width = indicators["bb_upper"] - indicators["bb_lower"]
        bb_width = bb_width / indicators["bb_middle"] if indicators["bb_middle"] else 0
        indicators["bb_width"] = round(bb_width, 4)

    for period in [7, 14, 21]:
        if len(high) >= period:
            tr = pd.concat([
                high - low,
                (high - close.shift(1)).abs(),
                (low - close.shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr = tr.rolling(period).mean()
            indicators[f"atr_{period}"] = round(float(atr.iloc[-1]), 4)

    if len(close) >= 14:
        low14 = low.rolling(14).min()
        high14 = high.rolling(14).max()
        stoch_k = 100 * (close - low14) / (high14 - low14).replace(0, np.nan)
        stoch_d = stoch_k.rolling(3).mean()
        indicators["stoch_k"] = round(float(stoch_k.iloc[-1]), 2) if not np.isnan(stoch_k.iloc[-1]) else 50.0
        indicators["stoch_d"] = round(float(stoch_d.iloc[-1]), 2) if not np.isnan(stoch_d.iloc[-1]) else 50.0

    if len(vol) >= 20:
        vol_sma20 = vol.rolling(20).mean()
        indicators["volume_sma_20"] = round(float(vol_sma20.iloc[-1]), 0)
        vol_ratio = float(vol.iloc[-1] / vol_sma20.iloc[-1]) if vol_sma20.iloc[-1] > 0 else 1.0
        indicators["volume_ratio"] = round(vol_ratio, 2)

    if len(close) >= 2:
        indicators["daily_return"] = round(float((close.iloc[-1] / close.iloc[-2] - 1) * 100), 4)
    if len(close) >= 20:
        returns = close.pct_change().dropna()
        indicators["volatility_20d"] = round(float(returns.tail(20).std() * (252 ** 0.5) * 100), 2)
    if len(close) >= 5:
        indicators["return_5d"] = round(float((close.iloc[-1] / close.iloc[-5] - 1) * 100), 2)

    if len(close) >= 50:
        high_52w = close.tail(min(252, len(close))).max()
        low_52w = close.tail(min(252, len(close))).min()
        indicators["distance_52w_high"] = round(float((close.iloc[-1] / high_52w - 1) * 100), 2)
        indicators["distance_52w_low"] = round(float((close.iloc[-1] / low_52w - 1) * 100), 2)

    return indicators


async def _fetch_ohlcv(ticker: str) -> dict[str, Any]:
    """Fetch OHLCV data via yfinance (run in executor to avoid blocking)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _fetch_ohlcv_sync, ticker)


def _fetch_ohlcv_sync(ticker: str) -> dict[str, Any]:
    try:
        import yfinance as yf
        data = yf.download(ticker, period="6mo", interval="1d", progress=False)
        if data.empty:
            return {}

        if hasattr(data.columns, "droplevel"):
            data.columns = data.columns.droplevel(1) if data.columns.nlevels > 1 else data.columns

        latest = data.iloc[-1]
        result = {
            "open": round(float(latest.get("Open", 0)), 4),
            "high": round(float(latest.get("High", 0)), 4),
            "low": round(float(latest.get("Low", 0)), 4),
            "close": round(float(latest.get("Close", 0)), 4),
            "volume": int(latest.get("Volume", 0)),
            "close_history": [round(float(x), 4) for x in data["Close"].tolist()],
            "high_history": [round(float(x), 4) for x in data["High"].tolist()],
            "low_history": [round(float(x), 4) for x in data["Low"].tolist()],
            "volume_history": [int(x) for x in data["Volume"].tolist()],
        }
        return result
    except Exception as exc:
        log.error("yfinance fetch failed for %s: %s", ticker, exc)
        return {}


async def _market_data_loop() -> None:
    """Continuously compute market data + technical indicators for watched tickers."""
    while True:
        tickers = _get_watched_tickers()
        async with _session_factory() as session:
            fs = FeatureStoreClient(session, _redis)
            for ticker in tickers:
                try:
                    ohlcv = await _fetch_ohlcv(ticker)
                    if not ohlcv:
                        continue

                    market_features = {
                        "open": ohlcv.get("open"),
                        "high": ohlcv.get("high"),
                        "low": ohlcv.get("low"),
                        "close": ohlcv.get("close"),
                        "volume": ohlcv.get("volume"),
                    }
                    await fs.write_features(ticker, "market_data", market_features, ttl_minutes=5)

                    technicals = _compute_technical_indicators(ohlcv)
                    if technicals:
                        await fs.write_features(ticker, "technical", technicals, ttl_minutes=5)

                    log.info("Updated features for %s: %d market + %d technical",
                             ticker, len(market_features), len(technicals))
                except Exception as exc:
                    log.error("Feature computation failed for %s: %s", ticker, exc)

        await asyncio.sleep(MARKET_POLL_INTERVAL)


async def _market_context_loop() -> None:
    """Compute broader market context features (VIX, sector ETFs, etc.)."""
    context_tickers = {
        "^VIX": "vix",
        "SPY": "spy_change",
        "QQQ": "qqq_change",
        "IWM": "iwm_change",
        "TLT": "tlt_change",
        "GLD": "gld_change",
    }
    while True:
        context_features: dict[str, Any] = {}
        for yticker, label in context_tickers.items():
            try:
                ohlcv = await _fetch_ohlcv(yticker)
                if ohlcv and ohlcv.get("close"):
                    context_features[label] = ohlcv["close"]
                    history = ohlcv.get("close_history", [])
                    if len(history) >= 2:
                        context_features[f"{label}_1d_pct"] = round(
                            (history[-1] / history[-2] - 1) * 100, 2
                        )
            except Exception as exc:
                log.warning("Context fetch failed for %s: %s", yticker, exc)

        if context_features:
            async with _session_factory() as session:
                fs = FeatureStoreClient(session, _redis)
                for ticker in _get_watched_tickers():
                    await fs.write_features(ticker, "market_context", context_features, ttl_minutes=10)
            log.info("Updated market context: %d features", len(context_features))

        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis
    try:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        await _redis.ping()
        log.info("Connected to Redis")
    except Exception as exc:
        log.warning("Redis unavailable, running without cache: %s", exc)
        _redis = None

    _bg_tasks.append(asyncio.create_task(_market_data_loop()))
    _bg_tasks.append(asyncio.create_task(_market_context_loop()))
    log.info("Feature pipelines started")

    yield

    for task in _bg_tasks:
        task.cancel()
    _bg_tasks.clear()
    if _redis:
        await _redis.aclose()


app = FastAPI(title="Phoenix Feature Pipeline", lifespan=lifespan)


@app.get("/health")
async def health():
    freshness = []
    try:
        async with _session_factory() as session:
            fs = FeatureStoreClient(session, _redis)
            freshness = await fs.get_feature_freshness()
    except Exception as exc:
        return {"status": "degraded", "error": str(exc)[:200]}
    return {
        "status": "ok",
        "redis_connected": _redis is not None,
        "watched_tickers": _get_watched_tickers(),
        "feature_freshness": freshness,
    }


@app.get("/features/{ticker}")
async def get_features(ticker: str):
    """Read all feature groups for a ticker, joined into single vector."""
    ticker_upper = ticker.upper()
    async with _session_factory() as session:
        fs = FeatureStoreClient(session, _redis)
        features = await fs.read_feature_view(ticker_upper)

        result = await session.execute(
            text(
                "SELECT MAX(computed_at) FROM feature_store_features WHERE ticker = :ticker"
            ),
            {"ticker": ticker_upper},
        )
        row = result.fetchone()
        newest_computed_at = row[0] if row else None

    now = datetime.now(timezone.utc)
    if newest_computed_at is not None:
        if newest_computed_at.tzinfo is None:
            newest_computed_at = newest_computed_at.replace(tzinfo=timezone.utc)
        fresh = (now - newest_computed_at) < timedelta(minutes=5)
    else:
        fresh = False

    return {
        "ticker": ticker_upper,
        "feature_count": len(features),
        "features": features,
        "fresh": fresh,
        "computed_at": newest_computed_at.isoformat() if newest_computed_at else None,
    }


@app.get("/features/{ticker}/{group}")
async def get_feature_group(ticker: str, group: str):
    """Read a specific feature group for a ticker."""
    async with _session_factory() as session:
        fs = FeatureStoreClient(session, _redis)
        features = await fs.read_features(ticker.upper(), group)
    return {
        "ticker": ticker.upper(),
        "feature_group": group,
        "features": features or {},
    }
