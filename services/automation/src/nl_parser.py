"""
Natural language to cron expression parser — converts human-readable
schedule descriptions into standard cron strings.

M2.8: Automation scheduling.
"""

import re

_WEEKDAY_MAP = {
    "monday": "1", "tuesday": "2", "wednesday": "3", "thursday": "4",
    "friday": "5", "saturday": "6", "sunday": "0",
    "mon": "1", "tue": "2", "wed": "3", "thu": "4",
    "fri": "5", "sat": "6", "sun": "0",
}

_PATTERNS: list[tuple[re.Pattern, callable]] = []


def _register(pattern: str):
    def decorator(fn):
        _PATTERNS.append((re.compile(pattern, re.IGNORECASE), fn))
        return fn
    return decorator


def _parse_time(text: str) -> tuple[int, int]:
    """Extract hour and minute from time strings like '9am', '14:30', '2:15pm'."""
    m = re.search(r"(\d{1,2}):(\d{2})\s*(am|pm)?", text, re.IGNORECASE)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if m.group(3) and m.group(3).lower() == "pm" and hour != 12:
            hour += 12
        elif m.group(3) and m.group(3).lower() == "am" and hour == 12:
            hour = 0
        return hour, minute

    m = re.search(r"(\d{1,2})\s*(am|pm)", text, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        if m.group(2).lower() == "pm" and hour != 12:
            hour += 12
        elif m.group(2).lower() == "am" and hour == 12:
            hour = 0
        return hour, 0

    m = re.search(r"(\d{1,2}):(\d{2})", text)
    if m:
        return int(m.group(1)), int(m.group(2))

    return 0, 0


@_register(r"every\s+(\d+)\s+minutes?")
def _every_n_minutes(m: re.Match, text: str) -> str:
    n = int(m.group(1))
    return f"*/{n} * * * *"


@_register(r"every\s+(\d+)\s+hours?")
def _every_n_hours(m: re.Match, text: str) -> str:
    n = int(m.group(1))
    return f"0 */{n} * * *"


@_register(r"every\s+weekday")
def _every_weekday(m: re.Match, text: str) -> str:
    hour, minute = _parse_time(text)
    return f"{minute} {hour} * * 1-5"


@_register(r"every\s+weekend")
def _every_weekend(m: re.Match, text: str) -> str:
    hour, minute = _parse_time(text)
    return f"{minute} {hour} * * 0,6"


@_register(r"every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)")
def _every_specific_day(m: re.Match, text: str) -> str:
    day = _WEEKDAY_MAP[m.group(1).lower()]
    hour, minute = _parse_time(text)
    return f"{minute} {hour} * * {day}"


@_register(r"every\s+day")
def _every_day(m: re.Match, text: str) -> str:
    hour, minute = _parse_time(text)
    return f"{minute} {hour} * * *"


@_register(r"every\s+hour")
def _every_hour(m: re.Match, text: str) -> str:
    return "0 * * * *"


@_register(r"every\s+minute")
def _every_minute(m: re.Match, text: str) -> str:
    return "* * * * *"


@_register(r"at\s+market\s+open")
def _market_open(m: re.Match, text: str) -> str:
    return "30 9 * * 1-5"


@_register(r"at\s+market\s+close")
def _market_close(m: re.Match, text: str) -> str:
    return "0 16 * * 1-5"


@_register(r"pre[-\s]?market")
def _premarket(m: re.Match, text: str) -> str:
    return "0 8 * * 1-5"


@_register(r"after[-\s]?hours")
def _afterhours(m: re.Match, text: str) -> str:
    return "0 17 * * 1-5"


def parse_schedule(text: str) -> str:
    """Convert natural language schedule description to a cron expression.

    Examples::

        parse_schedule("every weekday at 9am")       -> "0 9 * * 1-5"
        parse_schedule("every 5 minutes")             -> "*/5 * * * *"
        parse_schedule("every Monday at 2:30pm")      -> "30 14 * * 1"
        parse_schedule("at market open")              -> "30 9 * * 1-5"
    """
    text = text.strip()
    for pattern, handler in _PATTERNS:
        m = pattern.search(text)
        if m:
            return handler(m, text)

    raise ValueError(f"Could not parse schedule: {text!r}")
