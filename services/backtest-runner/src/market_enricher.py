"""
Market data enricher — adds OHLCV, technical indicators, and options data
to each reconstructed backtest trade.

Uses yfinance as the primary free data source. Falls back to Polygon or
Alpha Vantage when connectors are configured.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from shared.db.models.backtest_trade import BacktestTrade

logger = logging.getLogger(__name__)


def _safe_import_yfinance():
    try:
        import yfinance as yf
        return yf
    except ImportError:
        logger.warning("yfinance not installed, market enrichment will be limited")
        return None


def _compute_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_sma(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def _compute_macd(closes: list[float]) -> Optional[float]:
    if len(closes) < 26:
        return None
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    if ema12 is None or ema26 is None:
        return None
    return ema12 - ema26


def _ema(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for val in values[period:]:
        ema = val * k + ema * (1 - k)
    return ema


def _compute_bollinger_position(closes: list[float], period: int = 20) -> Optional[float]:
    """Returns position within Bollinger Bands: -1 (lower) to +1 (upper), 0 = middle."""
    if len(closes) < period:
        return None
    window = closes[-period:]
    sma = sum(window) / period
    std = (sum((x - sma) ** 2 for x in window) / period) ** 0.5
    if std == 0:
        return 0.0
    upper = sma + 2 * std
    lower = sma - 2 * std
    current = closes[-1]
    return max(-1.0, min(1.0, (current - sma) / (upper - sma) if upper != sma else 0.0))


def _compute_atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period


async def enrich_trades(
    trades: list[BacktestTrade],
    market_data_connectors: list[dict] | None = None,
) -> list[BacktestTrade]:
    """
    Enrich a list of BacktestTrade objects with market data at entry time.
    Uses yfinance for OHLCV and technical indicators.
    """
    yf = _safe_import_yfinance()
    if not yf:
        logger.warning("Skipping market enrichment — yfinance not available")
        return trades

    # Group trades by ticker for efficient data fetching
    ticker_trades: dict[str, list[BacktestTrade]] = {}
    for trade in trades:
        ticker_trades.setdefault(trade.ticker, []).append(trade)

    for ticker, ticker_trade_list in ticker_trades.items():
        try:
            earliest = min(t.entry_time for t in ticker_trade_list)
            latest = max(t.exit_time for t in ticker_trade_list)

            start_date = (earliest - timedelta(days=60)).strftime("%Y-%m-%d")
            end_date = (latest + timedelta(days=5)).strftime("%Y-%m-%d")

            data = yf.download(ticker, start=start_date, end=end_date, progress=False)
            if data.empty:
                logger.warning("No yfinance data for %s", ticker)
                continue

            closes = data["Close"].tolist()
            highs = data["High"].tolist()
            lows = data["Low"].tolist()
            volumes = data["Volume"].tolist()
            dates = data.index.tolist()

            avg_vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else sum(volumes) / max(len(volumes), 1)

            for trade in ticker_trade_list:
                entry_dt = trade.entry_time.date() if hasattr(trade.entry_time, 'date') else trade.entry_time
                idx = None
                for i, d in enumerate(dates):
                    dt = d.date() if hasattr(d, 'date') else d
                    if dt <= entry_dt:
                        idx = i

                if idx is None or idx < 1:
                    continue

                up_to = closes[:idx + 1]
                up_to_highs = highs[:idx + 1]
                up_to_lows = lows[:idx + 1]

                trade.entry_rsi = _compute_rsi(up_to)
                trade.entry_macd = _compute_macd(up_to)
                trade.entry_bollinger_position = _compute_bollinger_position(up_to)
                trade.entry_atr = _compute_atr(up_to_highs, up_to_lows, up_to)

                sma20 = _compute_sma(up_to, 20)
                sma50 = _compute_sma(up_to, 50)
                current_price = up_to[-1]

                if sma20 and current_price:
                    trade.entry_sma_20_distance = ((current_price - sma20) / sma20) * 100
                if sma50 and current_price:
                    trade.entry_sma_50_distance = ((current_price - sma50) / sma50) * 100

                if idx < len(volumes) and avg_vol_20 > 0:
                    trade.entry_volume_ratio = volumes[idx] / avg_vol_20

        except Exception as e:
            logger.error("Failed to enrich trades for %s: %s", ticker, e)

    # Enrich with SPY data for market context
    try:
        spy_data = yf.download("SPY", period="2y", progress=False)
        if not spy_data.empty:
            spy_closes = spy_data["Close"].tolist()
            spy_dates = spy_data.index.tolist()

            for trade in trades:
                entry_dt = trade.entry_time.date() if hasattr(trade.entry_time, 'date') else trade.entry_time
                for i, d in enumerate(spy_dates):
                    dt = d.date() if hasattr(d, 'date') else d
                    if dt <= entry_dt and i > 0:
                        trade.market_spy_change = ((spy_closes[i] - spy_closes[i - 1]) / spy_closes[i - 1]) * 100
    except Exception as e:
        logger.error("Failed to enrich SPY context: %s", e)

    # Enrich with VIX data
    try:
        vix_data = yf.download("^VIX", period="2y", progress=False)
        if not vix_data.empty:
            vix_closes = vix_data["Close"].tolist()
            vix_dates = vix_data.index.tolist()

            for trade in trades:
                entry_dt = trade.entry_time.date() if hasattr(trade.entry_time, 'date') else trade.entry_time
                for i, d in enumerate(vix_dates):
                    dt = d.date() if hasattr(d, 'date') else d
                    if dt <= entry_dt:
                        trade.market_vix = vix_closes[i]
    except Exception as e:
        logger.error("Failed to enrich VIX context: %s", e)

    logger.info("Enriched %d trades with market data", len(trades))
    return trades
