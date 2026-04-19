"""Signal parser — enhanced with OldProject regex patterns for percentage-sell support."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from shared.utils.signal_parser import parse_trade_signal

logger = logging.getLogger(__name__)


@dataclass
class ParsedSignal:
    ticker: Optional[str] = None
    direction: Optional[str] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None
    entry_price: Optional[float] = None
    option_type: Optional[str] = None
    quantity: int | str = 1
    is_percentage: bool = False
    confidence: float = 0.0
    raw_content: str = ""
    author: str = ""
    channel: str = ""


def parse_signal(content: str, author: str = "", channel: str = "") -> ParsedSignal | None:
    """Parse a Discord message into a structured signal using regex-only parsing.

    Extends shared.utils.signal_parser with OldProject percentage-sell patterns.
    Returns None if no valid signal (ticker + direction) is found.
    """
    result = parse_trade_signal(content)

    if not result.ticker or not result.direction:
        logger.debug("No actionable signal in: %.80s", content)
        return None

    # Extract quantity and percentage info from OldProject patterns
    quantity, is_percentage = _extract_quantity(content)

    return ParsedSignal(
        ticker=result.ticker,
        direction=result.direction.lower(),
        strike=result.strike_price,
        expiry=result.expiry_date,
        entry_price=result.entry_price,
        option_type=result.option_type,
        quantity=quantity,
        is_percentage=is_percentage,
        confidence=result.confidence,
        raw_content=content,
        author=author,
        channel=channel,
    )


def _extract_quantity(content: str) -> tuple[int | str, bool]:
    """Extract quantity from message, supporting absolute contracts and percentage.

    Examples:
        - "Bought 5 SPX 6940C" -> (5, False)
        - "Sold 50% SPX 6950C" -> ("50%", True)
        - "Bought SPX 6940C" -> (1, False)

    Returns (quantity, is_percentage).
    """
    content_upper = content.upper().strip()

    # Percentage pattern: "SOLD 50% ..." or "SELL 70% ..."
    pct_pattern = r"(?:BOUGHT|BUY|SOLD|SELL|BTO|STC)\s+(\d+)\s*%"
    pct_match = re.search(pct_pattern, content_upper)
    if pct_match:
        pct_value = pct_match.group(1)
        return f"{pct_value}%", True

    # Absolute quantity pattern: "BOUGHT 5 CONTRACTS" or "BUY 10 SPX"
    abs_pattern = r"(?:BOUGHT|BUY|SOLD|SELL|BTO|STC)\s+(\d+(?:\.\d+)?)\s*(?:CONTRACTS?|[A-Z]{1,5})"
    abs_match = re.search(abs_pattern, content_upper)
    if abs_match:
        try:
            qty = int(float(abs_match.group(1)))
            if qty > 0:
                return qty, False
        except ValueError:
            pass

    # Default: 1 contract
    return 1, False
