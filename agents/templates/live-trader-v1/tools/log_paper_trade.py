"""Paper trade logger -- records hypothetical trades without any real brokerage calls.

Usage:
    python tools/log_paper_trade.py \\
        --signal <path>           # path to enriched_signal.json
        --direction BUY|SELL      # trade direction
        --ticker TICKER           # underlying ticker symbol
        [--quantity N]            # number of shares / contracts
        [--price P]               # fill price (float)
        [--config config.json]    # agent config path

Output:
    Appends a trade record to paper_trades.json in the CWD.
    Prints a JSON summary to stdout.
    Always exits 0 -- never crashes the agent session.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PAPER_TRADES_FILE = Path("paper_trades.json")


def _load_config(config_path: str) -> dict:
    p = Path(config_path)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _load_signal(signal_path: str) -> dict:
    p = Path(signal_path)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            # Handle both list and dict signal formats
            if isinstance(data, list):
                return data[0] if data else {}
            return data
        except Exception:
            pass
    return {}


def _append_trade(record: dict) -> None:
    """Append a trade record to paper_trades.json."""
    existing: list = []
    if PAPER_TRADES_FILE.exists():
        try:
            existing = json.loads(PAPER_TRADES_FILE.read_text())
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    existing.append(record)
    PAPER_TRADES_FILE.write_text(json.dumps(existing, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="Log a paper trade (no real orders)")
    parser.add_argument("--signal", default=None, help="Path to enriched_signal.json")
    parser.add_argument("--direction", required=True, choices=["BUY", "SELL"],
                        help="Trade direction")
    parser.add_argument("--ticker", required=True, help="Underlying ticker symbol")
    parser.add_argument("--quantity", type=float, default=None,
                        help="Number of shares / contracts")
    parser.add_argument("--price", type=float, default=None,
                        help="Fill price")
    parser.add_argument("--config", default="config.json",
                        help="Agent config path (default: config.json)")
    args = parser.parse_args()

    try:
        cfg = _load_config(args.config)
        signal_data = _load_signal(args.signal) if args.signal else {}

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "paper",
            "direction": args.direction,
            "ticker": args.ticker,
            "quantity": args.quantity,
            "price": args.price,
            "agent_name": cfg.get("agent_name") or cfg.get("name", "unknown"),
            "connector_id": cfg.get("connector_id") or cfg.get("channel_id"),
            "signal_content": signal_data.get("content"),
            "signal_author": signal_data.get("author"),
            "confidence": signal_data.get("confidence"),
            "signal_ref": args.signal,
        }

        _append_trade(record)

        summary = {
            "status": "logged",
            "mode": "paper",
            "ticker": args.ticker,
            "direction": args.direction,
            "quantity": args.quantity,
            "price": args.price,
            "timestamp": record["timestamp"],
            "file": str(PAPER_TRADES_FILE),
        }
        print(json.dumps(summary))

    except Exception as exc:  # noqa: BLE001
        # Never crash the agent -- log error and exit 0
        print(json.dumps({
            "status": "error",
            "mode": "paper",
            "error": str(exc),
            "ticker": getattr(args, "ticker", "unknown"),
            "direction": getattr(args, "direction", "unknown"),
        }))


if __name__ == "__main__":
    main()
