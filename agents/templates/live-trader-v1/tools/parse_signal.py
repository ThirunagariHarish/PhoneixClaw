"""Parse a raw Discord message into a structured trade signal.

Extracts ticker, direction, price, option metadata (strike, type, expiry)
from free-text analyst messages.

Usage:
    python parse_signal.py --input signal.json --output parsed.json

Or import directly:
    from parse_signal import parse
    result = parse({"content": "BTO $AAPL 185c 4/18", "author": "vinod"})
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse(raw_signal: dict) -> dict:
    """Normalize a raw signal into a structured format.

    Returns a dict with: ticker, direction, signal_price, option_type,
    strike, expiry, raw_content, author, timestamp, message_id.
    """
    content = raw_signal.get("content", "")
    parsed: dict = {
        "raw_content": content,
        "author": raw_signal.get("author", "unknown"),
        "timestamp": raw_signal.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "message_id": raw_signal.get("message_id"),
        "channel_id": raw_signal.get("channel_id"),
    }

    ticker_match = re.search(r"\$([A-Z]{1,5})", content, re.IGNORECASE)
    if ticker_match:
        parsed["ticker"] = ticker_match.group(1).upper()

    price_match = re.search(r"@?\s*\$?([\d]+\.?\d*)", content)
    if price_match:
        parsed["signal_price"] = float(price_match.group(1))

    direction_patterns = {
        "buy": r"\b(buy|bought|long|calls?|entered|entry|bto)\b",
        "sell": r"\b(sell|sold|short|puts?|exit|close|trim|stc)\b",
    }
    for direction, pattern in direction_patterns.items():
        if re.search(pattern, content, re.IGNORECASE):
            parsed["direction"] = direction
            break

    option_match = re.search(r"(\d+\.?\d*)\s*([cp])\b", content, re.IGNORECASE)
    if option_match:
        parsed["strike"] = float(option_match.group(1))
        parsed["option_type"] = "call" if option_match.group(2).lower() == "c" else "put"

    expiry_match = re.search(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", content)
    if expiry_match:
        month = int(expiry_match.group(1))
        day = int(expiry_match.group(2))
        year = int(expiry_match.group(3)) if expiry_match.group(3) else datetime.now().year
        if year < 100:
            year += 2000
        try:
            parsed["expiry"] = f"{year}-{month:02d}-{day:02d}"
        except ValueError:
            pass

    return parsed


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse a raw signal into structured format")
    ap.add_argument("--input", required=True, help="Path to raw signal JSON")
    ap.add_argument("--output", default="parsed_signal.json", help="Output path")
    args = ap.parse_args()

    raw = json.loads(Path(args.input).read_text())
    if isinstance(raw, list):
        raw = raw[0] if raw else {}

    result = parse(raw)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps({
        "ticker": result.get("ticker"),
        "direction": result.get("direction"),
        "signal_price": result.get("signal_price"),
    }))


if __name__ == "__main__":
    main()
