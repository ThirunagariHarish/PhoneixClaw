"""Technical analysis — RSI, MACD, Bollinger Bands, ADX via yfinance."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

TICKER_MAP = {
    "SPX": "^GSPC",
    "NDX": "^NDX",
    "DJI": "^DJI",
    "VIX": "^VIX",
    "RUT": "^RUT",
}


@dataclass
class TAResult:
    rsi: Optional[float] = None
    macd_signal: str = "neutral"  # bullish | bearish | neutral
    bb_position: str = "within"  # above | below | within
    adx: Optional[float] = None
    overall_bias: str = "neutral"  # bullish | bearish | neutral
    confidence_adjustment: float = 0.0  # -0.2 to +0.2


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    val = rsi_series.iloc[-1]
    return float(val) if pd.notna(val) else 50.0


def _macd_signal(close: pd.Series) -> str:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    if len(macd_line) < 2:
        return "neutral"
    if macd_line.iloc[-1] > signal_line.iloc[-1]:
        return "bullish"
    elif macd_line.iloc[-1] < signal_line.iloc[-1]:
        return "bearish"
    return "neutral"


def _bb_position(close: pd.Series, window: int = 20, num_std: int = 2) -> str:
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    price = close.iloc[-1]
    if pd.isna(upper.iloc[-1]) or pd.isna(lower.iloc[-1]):
        return "within"
    if price >= upper.iloc[-1]:
        return "above"
    elif price <= lower.iloc[-1]:
        return "below"
    return "within"


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)

    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()

    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = dx.ewm(span=period, adjust=False).mean()
    val = adx_val.iloc[-1]
    return float(val) if pd.notna(val) else 0.0


def _compute_ta(ticker: str) -> TAResult:
    """Blocking TA computation — meant to run in a thread executor."""
    yf_ticker = TICKER_MAP.get(ticker.upper(), ticker)
    try:
        data = yf.download(yf_ticker, period="1mo", interval="1d", progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
    except Exception as exc:
        logger.warning("yfinance download failed for %s: %s", ticker, exc)
        return TAResult()

    if data.empty or len(data) < 14:
        logger.warning("Insufficient data for TA on %s (%d bars)", ticker, len(data))
        return TAResult()

    close = data["Close"]
    high = data["High"]
    low = data["Low"]

    rsi_val = _rsi(close, 14)
    macd_sig = _macd_signal(close)
    bb_pos = _bb_position(close, 20, 2)
    adx_val = _adx(high, low, close, 14)

    # Determine overall bias from individual signals
    bullish = 0
    bearish = 0

    if rsi_val < 30:
        bullish += 1
    elif rsi_val > 70:
        bearish += 1

    if macd_sig == "bullish":
        bullish += 1
    elif macd_sig == "bearish":
        bearish += 1

    if bb_pos == "below":
        bullish += 1
    elif bb_pos == "above":
        bearish += 1

    if bullish > bearish:
        bias = "bullish"
    elif bearish > bullish:
        bias = "bearish"
    else:
        bias = "neutral"

    # Confidence adjustment: strong signals get ±0.1–0.2, weak get ±0.05
    strength = abs(bullish - bearish) / max(bullish + bearish, 1)
    adj = strength * 0.2
    if bias == "bearish":
        adj = -adj

    return TAResult(
        rsi=round(rsi_val, 2),
        macd_signal=macd_sig,
        bb_position=bb_pos,
        adx=round(adx_val, 2),
        overall_bias=bias,
        confidence_adjustment=round(max(-0.2, min(0.2, adj)), 3),
    )


async def analyze(ticker: str) -> TAResult:
    """Run TA in a thread executor (yfinance is blocking I/O)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _compute_ta, ticker)
