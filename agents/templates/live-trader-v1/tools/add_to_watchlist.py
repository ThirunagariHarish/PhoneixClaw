"""Add a ticker to a watchlist via the Phoenix broker gateway.

Usage:
    python3 tools/add_to_watchlist.py --ticker PLTR --config config.json
    python3 tools/add_to_watchlist.py --ticker PLTR --watchlist "My List" --config config.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watchlist] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

BROKER_TIMEOUT = 15


def add_to_watchlist(ticker: str, watchlist_name: str, broker_url: str) -> dict:
    """Add ticker to broker-gateway watchlist via HTTP."""
    url = f"{broker_url.rstrip('/')}/watchlist"
    try:
        resp = httpx.post(url, json={"symbols": [ticker], "watchlist_name": watchlist_name}, timeout=BROKER_TIMEOUT)
        if resp.status_code >= 400:
            log.warning("Broker gateway returned %d: %s", resp.status_code, resp.text[:200])
            return {"status": "error", "error": resp.text[:200]}
        return resp.json()
    except httpx.ConnectError as exc:
        log.warning("Cannot reach broker gateway at %s: %s", broker_url, exc)
        return {"status": "error", "error": f"broker_gateway_unreachable: {exc}"}
    except Exception as exc:
        log.warning("Watchlist request failed: %s", exc)
        return {"status": "error", "error": str(exc)[:200]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Add ticker to watchlist via broker gateway")
    parser.add_argument("--ticker", required=True, help="Stock ticker symbol (e.g. PLTR)")
    parser.add_argument("--watchlist", default="Phoenix Paper", help="Watchlist name")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--strike", type=float, help="Option strike price (for logging)")
    parser.add_argument("--expiry", help="Option expiry date (for logging)")
    parser.add_argument("--option-type", help="call or put (for logging)")
    parser.add_argument("--price", type=float, help="Signal price (for logging)")
    parser.add_argument("--reason", default="manual", help="Reason for adding")
    parser.add_argument("--author", default="", help="Signal author")
    args = parser.parse_args()

    config: dict = {}
    config_path = Path(args.config)
    if config_path.exists():
        config = json.loads(config_path.read_text())

    broker_url = config.get("broker_gateway_url", "http://localhost:8040")
    result = add_to_watchlist(args.ticker, args.watchlist, broker_url)

    output = {
        "status": result.get("status", "ok"),
        "ticker": args.ticker,
        "watchlist": args.watchlist,
        "broker_result": result,
    }
    print(json.dumps(output, indent=2, default=str))

    watchlist_entry = {
        "ticker": args.ticker,
        "option_type": args.option_type,
        "strike": args.strike,
        "expiry": args.expiry,
        "signal_price": args.price,
        "author": args.author,
        "reason": args.reason,
        "watchlist": args.watchlist,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }
    wl_file = Path("watchlist_entries.json")
    try:
        existing = json.loads(wl_file.read_text()) if wl_file.exists() else []
    except Exception:
        existing = []
    existing.append(watchlist_entry)
    wl_file.write_text(json.dumps(existing, indent=2, default=str))


if __name__ == "__main__":
    main()
