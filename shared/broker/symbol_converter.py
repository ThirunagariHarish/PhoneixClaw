"""
Broker-aware index option → ETF option converter.

Some brokers (e.g. Alpaca) do not support index options like SPXW.
This module converts unsupported index options to their ETF equivalents
(e.g. SPX → SPY) so trades can still be executed.

The mapping is keyed by broker_type, making it easy to add or remove
conversions when new brokers are integrated.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

BROKER_UNSUPPORTED_INDEXES: dict[str, dict[str, dict]] = {
    "alpaca": {
        "SPX": {"etf": "SPY", "ratio": 10.0},
        "SPXW": {"etf": "SPY", "ratio": 10.0},
    },
}

SPY_STRIKE_INCREMENT = 0.50


def _round_strike(strike: float, increment: float) -> float:
    return round(round(strike / increment) * increment, 2)


def convert_index_to_etf(
    broker_type: str,
    ticker: str,
    strike: float,
    option_type: str,
    expiration: str,
    quantity: int = 1,
) -> dict | None:
    """Convert an index option to its ETF equivalent for a given broker.

    Returns a dict with converted fields plus originals for audit,
    or None if no conversion is needed.
    """
    mappings = BROKER_UNSUPPORTED_INDEXES.get(broker_type.lower(), {})
    entry = mappings.get(ticker.upper())
    if not entry:
        return None

    etf_ticker = entry["etf"]
    ratio = entry["ratio"]
    etf_strike = _round_strike(strike / ratio, SPY_STRIKE_INCREMENT)

    logger.info(
        "Index→ETF conversion: %s %.2f %s → %s %.2f %s (broker=%s, ratio=%.1f)",
        ticker, strike, option_type, etf_ticker, etf_strike, option_type,
        broker_type, ratio,
    )

    return {
        "ticker": etf_ticker,
        "strike": etf_strike,
        "option_type": option_type,
        "expiration": expiration,
        "quantity": quantity,
        "original_ticker": ticker.upper(),
        "original_strike": strike,
        "conversion_ratio": ratio,
    }
