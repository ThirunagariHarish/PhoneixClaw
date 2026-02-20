import re
from datetime import datetime
from typing import Any


def parse_trade_message(text: str) -> dict[str, Any]:
    """
    Parse trading messages to extract trade actions.

    Examples:
    - "Bought IWM 250P at 1.50 Exp: 02/20/2026"
    - "Bought SPX 6940C at 4.80"
    - "Sold 50% SPX 6950C at 6.50"
    """
    text_upper = text.upper().strip()
    actions: list[dict[str, Any]] = []

    expiration = _extract_expiration(text_upper)

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

    return {"actions": actions, "raw_message": text}


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
