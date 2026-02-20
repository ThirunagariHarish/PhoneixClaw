import json
import logging

from shared.config.base_config import config

logger = logging.getLogger(__name__)


def calculate_buffered_price(
    price: float,
    side: str,
    ticker: str | None = None,
    buffer_pct: float | None = None,
) -> tuple[float, float]:
    """
    Calculate buffered price for order execution.

    For BUY: price + buffer (willing to pay more to ensure fill)
    For SELL: price - buffer (willing to accept less to ensure fill)

    Returns (buffered_price, buffer_pct_used).
    """
    overrides: dict[str, float] = {}
    try:
        overrides = json.loads(config.execution.buffer_overrides)
    except (json.JSONDecodeError, TypeError):
        pass

    pct = buffer_pct if buffer_pct is not None else config.execution.buffer_percentage

    if ticker and ticker.upper() in overrides:
        pct = overrides[ticker.upper()]

    pct = min(pct, config.execution.buffer_max_percentage)
    pct = max(pct, 0.0)

    buffer_amount = price * pct
    buffer_amount = max(buffer_amount, config.execution.buffer_min_price)

    if side.upper() == "BUY":
        buffered = price + buffer_amount
    else:
        buffered = max(price - buffer_amount, config.execution.buffer_min_price)

    buffered = round(buffered, 2)
    actual_pct = round(abs(buffered - price) / price, 4) if price > 0 else 0.0

    return buffered, actual_pct
