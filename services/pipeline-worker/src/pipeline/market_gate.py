"""Market hours gate — determines if US equity markets are open."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from shared.utils.market_calendar import (
    get_market_status,
    is_market_open,
    next_market_close,
    next_market_open,
)

logger = logging.getLogger(__name__)


@dataclass
class MarketStatus:
    is_open: bool
    session_type: str  # "premarket" | "regular" | "afterhours" | "closed"
    opens_at: Optional[str] = None
    closes_at: Optional[str] = None


def check_market_hours() -> MarketStatus:
    """Check current US market session status using shared calendar."""
    status = get_market_status()
    session = status["session"]

    close_dt = next_market_close()
    open_dt = next_market_open()

    return MarketStatus(
        is_open=is_market_open(),
        session_type=session,
        opens_at=open_dt.isoformat() if open_dt else None,
        closes_at=close_dt.isoformat() if close_dt else None,
    )
