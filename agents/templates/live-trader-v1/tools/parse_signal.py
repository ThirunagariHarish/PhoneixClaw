"""Parse a raw Discord message into a structured trade signal.

Extracts ticker, direction, price, option metadata (strike, type, expiry)
from free-text analyst messages using the intelligent multi-layer parser.

Usage:
    python parse_signal.py --input signal.json --output parsed.json

Or import directly:
    from parse_signal import parse
    result = parse({"content": "BTO $AAPL 185c 4/18", "author": "vinod"})
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# Use the shared intelligent parser (backward-compatible wrapper)
from shared.utils.signal_parser import parse_signal_compat


def parse(raw_signal: dict) -> dict:
    """Normalize a raw signal into a structured format.

    Returns a dict with: ticker, direction, signal_price, option_type,
    strike, expiry, raw_content, author, timestamp, message_id.

    Delegates to shared.utils.signal_parser for robust multi-format parsing.
    """
    return parse_signal_compat(raw_signal)


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
