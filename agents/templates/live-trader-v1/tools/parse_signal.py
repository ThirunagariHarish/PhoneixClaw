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
import logging
import os
import sys
from pathlib import Path

# Use the shared intelligent parser (backward-compatible wrapper)
from shared.utils.signal_parser import parse_signal_compat

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [parse_signal] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


def parse(raw_signal: dict) -> dict:
    """Normalize a raw signal into a structured format.

    Returns a dict with: ticker, direction, signal_price, option_type,
    strike, expiry, raw_content, author, timestamp, message_id.

    Delegates to shared.utils.signal_parser for robust multi-format parsing.
    """
    correlation_id = raw_signal.get("correlation_id") or os.getenv("CORRELATION_ID")
    if correlation_id:
        log.info("Parsing signal", extra={"correlation_id": correlation_id})
    result = parse_signal_compat(raw_signal)
    if correlation_id:
        result["correlation_id"] = correlation_id
    return result


async def _write_dlq(connector_id: str, payload: dict, error: str) -> None:
    """Write failed signal to dead_letter_messages table."""
    try:
        from sqlalchemy import text

        from shared.db.engine import get_session
        async for session in get_session():
            await session.execute(
                text("INSERT INTO dead_letter_messages (connector_id, payload, error) VALUES (:cid, :payload, :error)"),
                {"cid": connector_id, "payload": json.dumps(payload), "error": error[:500]},
            )
            await session.commit()
            log.warning("DLQ write succeeded for connector %s", connector_id, extra={"correlation_id": payload.get("correlation_id")})
    except Exception as dlq_exc:
        log.error("DLQ write failed: %s", dlq_exc)


def main() -> None:
    ap = argparse.ArgumentParser(description="Parse a raw signal into structured format")
    ap.add_argument("--input", required=True, help="Path to raw signal JSON")
    ap.add_argument("--output", default="parsed_signal.json", help="Output path")
    ap.add_argument("--config", help="Path to config.json for connector_id")
    args = ap.parse_args()

    try:
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
    except Exception as exc:
        log.error("parse_signal failed: %s", exc, exc_info=True)
        connector_id = "unknown"
        if args.config and Path(args.config).exists():
            try:
                cfg = json.loads(Path(args.config).read_text())
                connector_id = cfg.get("connector_id", "unknown")
            except Exception:
                pass
        import asyncio
        asyncio.run(_write_dlq(connector_id, raw if 'raw' in locals() else {}, str(exc)))
        sys.exit(1)


if __name__ == "__main__":
    main()
