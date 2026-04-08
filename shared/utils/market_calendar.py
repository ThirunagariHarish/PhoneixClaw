"""
Market calendar utilities for US equity markets.

Simple rule-based implementation; use shared.market.calendar for full exchange support.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

US_EASTERN = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)


def _now_et() -> datetime:
    return datetime.now(US_EASTERN)


def is_trading_day(d: date | datetime | None = None) -> bool:
    """True if the given date is a US market trading day (Mon–Fri)."""
    if d is None:
        d = _now_et().date()
    elif isinstance(d, datetime):
        d = d.astimezone(US_EASTERN).date()
    return d.weekday() < 5


def is_market_open(dt: datetime | None = None) -> bool:
    """True if market is in regular trading hours (9:30–16:00 ET)."""
    dt = dt or _now_et()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=US_EASTERN)
    et = dt.astimezone(US_EASTERN)
    return is_trading_day(et) and REGULAR_OPEN <= et.time() < REGULAR_CLOSE


def next_market_open(dt: datetime | None = None) -> datetime:
    """Return next regular market open (9:30 ET) on a trading day."""
    dt = dt or _now_et()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=US_EASTERN)
    et = dt.astimezone(US_EASTERN)
    candidate = et.replace(hour=9, minute=30, second=0, microsecond=0)
    if et.time() >= REGULAR_CLOSE or not is_trading_day(et):
        candidate += timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def next_market_close(dt: datetime | None = None) -> datetime | None:
    """Return next market close (16:00 ET) if market is open, else None."""
    dt = dt or _now_et()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=US_EASTERN)
    et = dt.astimezone(US_EASTERN)
    if not is_trading_day(et) or et.time() >= REGULAR_CLOSE:
        return None
    return et.replace(hour=16, minute=0, second=0, microsecond=0)
