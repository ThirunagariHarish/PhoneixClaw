"""
Market hours utilities for US equity and options markets.

Uses exchange_calendars when available, falls back to simple rules otherwise.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

US_EASTERN = ZoneInfo("America/New_York")

REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
PREMARKET_OPEN = time(4, 0)
AFTERHOURS_CLOSE = time(20, 0)

_exchange_cal = None


class MarketSession(str, Enum):
    PREMARKET = "premarket"
    REGULAR = "regular"
    AFTERHOURS = "afterhours"
    CLOSED = "closed"


class MarketHoursMode(str, Enum):
    REGULAR_ONLY = "regular_only"
    EXTENDED = "extended"
    TWENTY_FOUR_SEVEN = "24_7"
    QUEUE = "queue"


def _get_exchange_calendar():
    global _exchange_cal
    if _exchange_cal is not None:
        return _exchange_cal
    try:
        import exchange_calendars as xcals
        _exchange_cal = xcals.get_calendar("XNYS")
        logger.info("Loaded NYSE exchange calendar")
        return _exchange_cal
    except ImportError:
        logger.warning("exchange_calendars not installed; using simple rules")
        return None
    except Exception as e:
        logger.warning("Failed to load exchange calendar: %s", e)
        return None


class MarketCalendar:
    """Provides market hours checking for the US equity market."""

    def __init__(self):
        self._cal = _get_exchange_calendar()

    def _now_et(self) -> datetime:
        return datetime.now(US_EASTERN)

    def current_session(self, dt: datetime | None = None) -> MarketSession:
        """Return the current market session."""
        dt = dt or self._now_et()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=US_EASTERN)
        et = dt.astimezone(US_EASTERN)

        if not self._is_trading_day(et):
            return MarketSession.CLOSED

        t = et.time()
        if REGULAR_OPEN <= t < REGULAR_CLOSE:
            return MarketSession.REGULAR
        elif PREMARKET_OPEN <= t < REGULAR_OPEN:
            return MarketSession.PREMARKET
        elif REGULAR_CLOSE <= t < AFTERHOURS_CLOSE:
            return MarketSession.AFTERHOURS
        else:
            return MarketSession.CLOSED

    def is_market_open(self, dt: datetime | None = None) -> bool:
        """True if the market is in regular trading hours."""
        return self.current_session(dt) == MarketSession.REGULAR

    def is_premarket(self, dt: datetime | None = None) -> bool:
        return self.current_session(dt) == MarketSession.PREMARKET

    def is_afterhours(self, dt: datetime | None = None) -> bool:
        return self.current_session(dt) == MarketSession.AFTERHOURS

    def is_extended_hours(self, dt: datetime | None = None) -> bool:
        session = self.current_session(dt)
        return session in (MarketSession.PREMARKET, MarketSession.AFTERHOURS)

    def should_trade(self, mode: MarketHoursMode, dt: datetime | None = None) -> bool:
        """Check if trading should occur given the configured mode."""
        if mode == MarketHoursMode.TWENTY_FOUR_SEVEN:
            return True
        session = self.current_session(dt)
        if mode == MarketHoursMode.REGULAR_ONLY:
            return session == MarketSession.REGULAR
        if mode == MarketHoursMode.EXTENDED:
            return session in (MarketSession.PREMARKET, MarketSession.REGULAR, MarketSession.AFTERHOURS)
        if mode == MarketHoursMode.QUEUE:
            return True  # queue mode always accepts but delays execution
        return False

    def next_market_open(self, dt: datetime | None = None) -> datetime:
        """Return the next regular market open datetime (ET)."""
        dt = dt or self._now_et()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=US_EASTERN)
        et = dt.astimezone(US_EASTERN)

        if self._cal:
            try:
                import pandas as pd
                ts = pd.Timestamp(et)
                next_session = self._cal.next_open(ts)
                return next_session.to_pydatetime().replace(tzinfo=timezone.utc).astimezone(US_EASTERN)
            except Exception:
                pass

        candidate = et.replace(hour=9, minute=30, second=0, microsecond=0)
        if et.time() >= REGULAR_CLOSE or not self._is_trading_day(et):
            candidate += timedelta(days=1)
        while not self._is_trading_day(candidate):
            candidate += timedelta(days=1)
        return candidate

    def time_until_open(self, dt: datetime | None = None) -> timedelta:
        """Return timedelta until next market open."""
        dt = dt or self._now_et()
        next_open = self.next_market_open(dt)
        return next_open - dt.astimezone(US_EASTERN)

    def time_until_close(self, dt: datetime | None = None) -> timedelta | None:
        """Return timedelta until market close, or None if not open."""
        dt = dt or self._now_et()
        if not self.is_market_open(dt):
            return None
        et = dt.astimezone(US_EASTERN)
        close = et.replace(hour=16, minute=0, second=0, microsecond=0)
        return close - et

    def _is_trading_day(self, dt: datetime) -> bool:
        """Check if the given date is a trading day."""
        if self._cal:
            try:
                import pandas as pd
                ts = pd.Timestamp(dt.date())
                return self._cal.is_session(ts)
            except Exception:
                pass
        return dt.weekday() < 5
