from __future__ import annotations

"""
Market calendar utilities for US equity markets (NYSE/NASDAQ).

Features:
  - Regular hours: 9:30-16:00 ET
  - Pre-market: 4:00-9:30 ET
  - After-hours: 16:00-20:00 ET
  - US market holidays (2024-2027)
  - Early close days (1:00 PM ET)
  - Adaptive interval recommendations for position monitors
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

US_EASTERN = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
PREMARKET_OPEN = time(4, 0)
AFTERHOURS_CLOSE = time(20, 0)
EARLY_CLOSE = time(13, 0)

# NYSE holidays (fixed dates + observed rules)
# Regenerate yearly or use exchange_calendars package for production
_HOLIDAYS: set[date] = {
    # 2024
    date(2024, 1, 1), date(2024, 1, 15), date(2024, 2, 19),
    date(2024, 3, 29), date(2024, 5, 27), date(2024, 6, 19),
    date(2024, 7, 4), date(2024, 9, 2), date(2024, 11, 28),
    date(2024, 12, 25),
    # 2025
    date(2025, 1, 1), date(2025, 1, 20), date(2025, 2, 17),
    date(2025, 4, 18), date(2025, 5, 26), date(2025, 6, 19),
    date(2025, 7, 4), date(2025, 9, 1), date(2025, 11, 27),
    date(2025, 12, 25),
    # 2026
    date(2026, 1, 1), date(2026, 1, 19), date(2026, 2, 16),
    date(2026, 4, 3), date(2026, 5, 25), date(2026, 6, 19),
    date(2026, 7, 3), date(2026, 9, 7), date(2026, 11, 26),
    date(2026, 12, 25),
    # 2027
    date(2027, 1, 1), date(2027, 1, 18), date(2027, 2, 15),
    date(2027, 3, 26), date(2027, 5, 31), date(2027, 6, 18),
    date(2027, 7, 5), date(2027, 9, 6), date(2027, 11, 25),
    date(2027, 12, 24),
}

# Early close days (1:00 PM ET) — day before July 4th, day after Thanksgiving, Christmas Eve
_EARLY_CLOSE_DATES: set[date] = {
    date(2024, 7, 3), date(2024, 11, 29), date(2024, 12, 24),
    date(2025, 7, 3), date(2025, 11, 28), date(2025, 12, 24),
    date(2026, 7, 2), date(2026, 11, 27), date(2026, 12, 24),
    date(2027, 7, 2), date(2027, 11, 26), date(2027, 12, 23),
}


def _now_et() -> datetime:
    return datetime.now(US_EASTERN)


def _to_date(d: date | datetime | None) -> date:
    if d is None:
        return _now_et().date()
    if isinstance(d, datetime):
        return d.astimezone(US_EASTERN).date()
    return d


def is_holiday(d: date | datetime | None = None) -> bool:
    """True if the date is a US market holiday."""
    return _to_date(d) in _HOLIDAYS


def is_early_close(d: date | datetime | None = None) -> bool:
    """True if the date is an early close day (1:00 PM ET)."""
    return _to_date(d) in _EARLY_CLOSE_DATES


def is_trading_day(d: date | datetime | None = None) -> bool:
    """True if the given date is a US market trading day (Mon-Fri, not a holiday)."""
    dt = _to_date(d)
    return dt.weekday() < 5 and dt not in _HOLIDAYS


def is_market_open(dt: datetime | None = None) -> bool:
    """True if market is in regular trading hours (9:30-16:00 ET, or 9:30-13:00 on early close)."""
    dt = dt or _now_et()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=US_EASTERN)
    et = dt.astimezone(US_EASTERN)
    if not is_trading_day(et):
        return False
    close = EARLY_CLOSE if is_early_close(et) else REGULAR_CLOSE
    return REGULAR_OPEN <= et.time() < close


def is_premarket(dt: datetime | None = None) -> bool:
    """True if in pre-market hours (4:00-9:30 ET on a trading day)."""
    dt = dt or _now_et()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=US_EASTERN)
    et = dt.astimezone(US_EASTERN)
    return is_trading_day(et) and PREMARKET_OPEN <= et.time() < REGULAR_OPEN


def is_afterhours(dt: datetime | None = None) -> bool:
    """True if in after-hours (16:00-20:00 ET on a trading day, or 13:00-20:00 on early close)."""
    dt = dt or _now_et()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=US_EASTERN)
    et = dt.astimezone(US_EASTERN)
    if not is_trading_day(et):
        return False
    close = EARLY_CLOSE if is_early_close(et) else REGULAR_CLOSE
    return close <= et.time() < AFTERHOURS_CLOSE


def is_extended_hours(dt: datetime | None = None) -> bool:
    """True if in any trading session (pre-market, regular, or after-hours)."""
    return is_premarket(dt) or is_market_open(dt) or is_afterhours(dt)


def get_market_status(dt: datetime | None = None) -> dict:
    """Human-readable market state for dashboards, enrichment, and routing.

    Returns:
        summary: one-line status for logs/UI
        session: "regular" | "premarket" | "afterhours" | "closed"
        regular_session_open: True only during 9:30–16:00 ET regular hours
        extended_session_open: pre-market, regular, or after-hours on a trading day
        is_trading_day: Mon–Fri and not a holiday
        next_regular_open_et: ISO timestamp for next 9:30 ET open
        features_flat: flat dict for trade-signal / enrich JSON
        step_meta: compact dict for pipeline step records
    """
    dt = dt or _now_et()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=US_EASTERN)
    et = dt.astimezone(US_EASTERN)
    td = is_trading_day(et)
    reg = is_market_open(et)
    pre = is_premarket(et)
    ah = is_afterhours(et)
    ext = is_extended_hours(et)

    if reg:
        session = "regular"
        summary = "Market open (regular session 9:30 AM – 4:00 PM ET)."
    elif pre:
        session = "premarket"
        summary = "Pre-market session (outside regular hours). Regular session opens 9:30 AM ET."
    elif ah:
        session = "afterhours"
        summary = "After-hours session (outside regular hours)."
    elif not td:
        session = "closed"
        summary = "Market closed (weekend or holiday). Next regular session see next_regular_open_et."
    else:
        session = "closed"
        summary = "Market closed (outside trading hours). Next regular session see next_regular_open_et."

    nxt = next_market_open(et)
    features_flat = {
        "market_regular_session_open": float(reg),
        "market_extended_session_open": float(ext),
        "market_session": session,
        "market_status_label": summary,
        "market_is_trading_day": float(td),
        "market_next_regular_open_et": nxt.isoformat(),
    }
    step_meta = {
        "session": session,
        "regular_session_open": reg,
        "extended_session_open": ext,
        "is_trading_day": td,
        "summary": summary,
    }
    return {
        "summary": summary,
        "session": session,
        "regular_session_open": reg,
        "extended_session_open": ext,
        "is_trading_day": td,
        "next_regular_open_et": nxt.isoformat(),
        "features_flat": features_flat,
        "step_meta": step_meta,
    }


def next_market_open(dt: datetime | None = None) -> datetime:
    """Return next regular market open (9:30 ET) on a trading day."""
    dt = dt or _now_et()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=US_EASTERN)
    et = dt.astimezone(US_EASTERN)
    candidate = et.replace(hour=9, minute=30, second=0, microsecond=0)
    if et.time() >= REGULAR_OPEN or not is_trading_day(et):
        candidate += timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def next_market_close(dt: datetime | None = None) -> datetime | None:
    """Return next market close if market is open, else None."""
    dt = dt or _now_et()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=US_EASTERN)
    et = dt.astimezone(US_EASTERN)
    if not is_market_open(et):
        return None
    close = EARLY_CLOSE if is_early_close(et) else REGULAR_CLOSE
    return et.replace(hour=close.hour, minute=close.minute, second=0, microsecond=0)


def minutes_until_close(dt: datetime | None = None) -> float | None:
    """Minutes remaining until market close. None if not open."""
    close = next_market_close(dt)
    if close is None:
        return None
    dt = dt or _now_et()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=US_EASTERN)
    return (close - dt.astimezone(US_EASTERN)).total_seconds() / 60


def recommended_check_interval(dt: datetime | None = None) -> int:
    """Recommended position check interval in seconds based on market state.

    Returns:
        30  — during regular hours with <30 min to close (power hour urgency)
        120 — during regular hours (normal)
        300 — during pre-market or after-hours
        900 — market closed (overnight/weekend/holiday)
    """
    dt = dt or _now_et()

    if is_market_open(dt):
        remaining = minutes_until_close(dt)
        if remaining is not None and remaining < 30:
            return 30  # Power hour — check frequently
        return 120  # Normal market hours

    if is_premarket(dt) or is_afterhours(dt):
        return 300  # Extended hours — less frequent

    return 900  # Market closed
