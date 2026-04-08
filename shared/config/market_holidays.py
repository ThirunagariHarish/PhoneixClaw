"""US Market Holidays for 2025–2026 (NYSE calendar)."""

from __future__ import annotations

from datetime import date

MARKET_HOLIDAYS_2025: list[date] = [
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 20),  # MLK Day
    date(2025, 2, 17),  # Presidents Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),   # Independence Day
    date(2025, 9, 1),   # Labor Day
    date(2025, 11, 27), # Thanksgiving
    date(2025, 12, 25), # Christmas
]

MARKET_HOLIDAYS_2026: list[date] = [
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 8, 31),  # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
]

ALL_MARKET_HOLIDAYS: set[date] = set(MARKET_HOLIDAYS_2025 + MARKET_HOLIDAYS_2026)


def is_market_holiday(d: date) -> bool:
    """Return True if *d* is a NYSE market holiday."""
    return d in ALL_MARKET_HOLIDAYS


def is_trading_day(d: date) -> bool:
    """Return True if *d* is a weekday that is not a market holiday."""
    return d.weekday() < 5 and not is_market_holiday(d)
