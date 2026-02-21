import re
from datetime import datetime, timedelta
from typing import Any


def parse_trade_message(text: str) -> dict[str, Any]:
    """
    Parse trading messages to extract trade actions.

    Supported formats:
    - "BTO AAPL 190C 3/21 @ 2.50"
    - "STC AAPL 190C @ 3.00"
    - "Bought IWM 250P at 1.50 Exp: 02/20/2026"
    - "Sold 50% SPX 6950C at 6.50"
    - Time references: "0DTE", "weekly", "4hr", "2 week"
    """
    text_upper = text.upper().strip()
    actions: list[dict[str, Any]] = []

    expiration = _extract_expiration(text_upper)

    timeframe = extract_timeframe(text_upper)
    inferred_expiration = None
    if not expiration and timeframe:
        days = timeframe["days_offset"]
        inferred_expiration = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        expiration = inferred_expiration

    # BTO/STC/BTC/STO compact format: "BTO AAPL 190C 3/21 @ 2.50"
    compact_pattern = (
        r"(BTO|BTC|STO|STC)"
        r"\s+(?:(\d+)\s+)?"
        r"([A-Z]{1,5})\s+"
        r"(\d+(?:\.\d+)?)([CP])"
        r"(?:\s+(\d{1,2})[\/\-](\d{1,2})(?:[\/\-](\d{2,4}))?)?"
        r"\s*[@]\s*\$?(\d+(?:\.\d+)?)"
    )

    for match in re.finditer(compact_pattern, text_upper):
        action_code = match.group(1)
        side = "BUY" if action_code in ("BTO", "BTC") else "SELL"
        qty = int(match.group(2)) if match.group(2) else 1
        ticker = match.group(3)
        strike = float(match.group(4))
        opt_type = "CALL" if match.group(5) == "C" else "PUT"
        price = float(match.group(9))

        exp = expiration
        if match.group(6) and match.group(7):
            m, d = int(match.group(6)), int(match.group(7))
            if match.group(8):
                y = int(match.group(8))
                y = y if y >= 100 else 2000 + y
            else:
                y = datetime.now().year
            try:
                exp = datetime(y, m, d).strftime("%Y-%m-%d")
            except ValueError:
                pass

        actions.append({
            "action": side,
            "ticker": ticker,
            "strike": strike,
            "option_type": opt_type,
            "expiration": exp,
            "quantity": qty,
            "price": price,
            "is_percentage": False,
        })

    if actions:
        result: dict[str, Any] = {"actions": actions, "raw_message": text}
        if timeframe:
            result["timeframe"] = timeframe
        if inferred_expiration:
            result["inferred_expiration"] = True
        return result

    # Legacy verbose format: "Bought AAPL 190C at 2.50"
    buy_pattern = (
        r"(?:BOUGHT|BUY)\s+(?:(\d+(?:\.\d+)?)\s*(?:CONTRACTS?)?|(\d+)%)?"
        r"\s*([A-Z]{1,5})\s+(\d+(?:\.\d+)?)([CP])\s+(?:AT\s+)?\$?(\d+(?:\.\d+)?)"
    )
    sell_pattern = (
        r"(?:SOLD|SELL)\s+(?:(\d+(?:\.\d+)?)\s*(?:CONTRACTS?)?|(\d+)%)?"
        r"\s*([A-Z]{1,5})\s+(\d+(?:\.\d+)?)([CP])\s+(?:AT\s+)?\$?(\d+(?:\.\d+)?)"
    )

    for match in re.finditer(buy_pattern, text_upper):
        action = _build_action("BUY", match, expiration)
        if action:
            actions.append(action)

    for match in re.finditer(sell_pattern, text_upper):
        action = _build_action("SELL", match, expiration)
        if action:
            actions.append(action)

    result2: dict[str, Any] = {"actions": actions, "raw_message": text}
    if timeframe:
        result2["timeframe"] = timeframe
    if inferred_expiration:
        result2["inferred_expiration"] = True
    return result2


def _extract_expiration(text: str) -> str | None:
    patterns = [
        r"EXP:\s*(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})",
        r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{2,4})",
    ]
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            m, d, y = match.group(1), match.group(2), match.group(3)
            year = int(y) if len(y) == 4 else 2000 + int(y)
            try:
                return datetime(year, int(m), int(d)).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


_TIMEFRAME_MAP = {
    "0DTE": 0,
    "0 DTE": 0,
    "SAME DAY": 0,
    "1DTE": 1,
    "1 DTE": 1,
    "NEXT DAY": 1,
    "DAILY": 1,
    "2DTE": 2,
    "3DTE": 3,
    "WEEKLY": 5,
    "WEEKLIES": 5,
    "1W": 5,
    "2W": 10,
    "BIWEEKLY": 10,
    "MONTHLY": 30,
    "1M": 30,
    "2M": 60,
    "QUARTERLY": 90,
    "3M": 90,
    "6M": 180,
    "YEARLY": 365,
    "1Y": 365,
    "LEAPS": 365,
    "LEAP": 365,
}

_RELATIVE_TIME_PATTERN = re.compile(
    r"(\d+)\s*(?:HR|HOUR|H)\b", re.IGNORECASE
)
_DAY_PATTERN = re.compile(
    r"(\d+)\s*(?:DAY|D|DTE)\b", re.IGNORECASE
)
_WEEK_PATTERN = re.compile(
    r"(\d+)\s*(?:WEEK|WK|W)\b", re.IGNORECASE
)
_MONTH_PATTERN = re.compile(
    r"(\d+)\s*(?:MONTH|MO|M)\b", re.IGNORECASE
)


def extract_timeframe(text: str) -> dict[str, Any] | None:
    """Parse time-reference hints like '4hr', 'weekly', '0DTE', '2 week' from messages.

    Returns a dict with 'label' and 'days_offset' or None if no match.
    """
    upper = text.upper().strip()

    for label, days in _TIMEFRAME_MAP.items():
        if label in upper:
            return {"label": label, "days_offset": days}

    match = _DAY_PATTERN.search(upper)
    if match:
        d = int(match.group(1))
        return {"label": f"{d}DTE", "days_offset": d}

    match = _WEEK_PATTERN.search(upper)
    if match:
        w = int(match.group(1))
        return {"label": f"{w}W", "days_offset": w * 7}

    match = _MONTH_PATTERN.search(upper)
    if match:
        m = int(match.group(1))
        return {"label": f"{m}M", "days_offset": m * 30}

    match = _RELATIVE_TIME_PATTERN.search(upper)
    if match:
        return {"label": f"{match.group(1)}HR", "days_offset": 0}

    return None


def _build_action(side: str, match: re.Match, expiration: str | None) -> dict[str, Any] | None:  # type: ignore[type-arg]
    absolute_qty = match.group(1)
    percentage_qty = match.group(2)
    ticker = match.group(3)
    strike = float(match.group(4))
    option_type = "CALL" if match.group(5) == "C" else "PUT"
    price_str = match.group(6)
    if price_str is None:
        return None
    price = float(price_str)

    if percentage_qty:
        quantity: int | str = f"{percentage_qty}%"
        is_percentage = True
    elif absolute_qty:
        quantity = int(float(absolute_qty))
        is_percentage = False
    else:
        quantity = 1
        is_percentage = False

    return {
        "action": side,
        "ticker": ticker,
        "strike": strike,
        "option_type": option_type,
        "expiration": expiration,
        "quantity": quantity,
        "price": price,
        "is_percentage": is_percentage,
    }
