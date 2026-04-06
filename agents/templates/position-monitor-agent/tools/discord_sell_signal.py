"""Discord sell signal detector for position monitoring.

Watches the parent analyst's Discord channel for sell/close/trim mentions
of the assigned ticker and increases exit urgency if found.

Usage:
    python discord_sell_signal.py --ticker AAPL --since-minutes 30 --output sell.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SELL_PATTERNS = [
    r"\bsell(?:ing)?\b", r"\bsold\b", r"\bclose(?:d|ing)?\b",
    r"\btrim(?:med|ming)?\b", r"\bexit(?:ed|ing)?\b",
    r"\btake profit", r"\bcash out", r"\bout of\b",
]


def check_sell_signal(ticker: str, since_minutes: int = 30) -> dict:
    """Check the parent's Discord channel for sell mentions of this ticker."""
    result = {
        "ticker": ticker,
        "exit_urgency": 0,
        "messages_found": [],
        "since_minutes": since_minutes,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Read position config to get parent agent's discord credentials
    try:
        config = json.loads(Path("config.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        result["error"] = "config.json not found"
        return result

    discord_token = config.get("discord_token") or os.getenv("DISCORD_TOKEN", "")
    channel_id = config.get("channel_id") or os.getenv("DISCORD_CHANNEL_ID", "")

    if not discord_token or not channel_id:
        result["error"] = "Discord token or channel_id missing"
        return result

    try:
        import httpx

        # Discord REST API: GET channel messages
        # https://discord.com/developers/docs/resources/channel#get-channel-messages
        url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=50"
        headers = {"Authorization": f"Bot {discord_token}"} if not discord_token.startswith("user_") else {"Authorization": discord_token}

        resp = httpx.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            result["error"] = f"Discord API returned {resp.status_code}"
            return result

        messages = resp.json()
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)

        ticker_pattern = re.compile(rf"\${ticker}\b|\b{ticker}\b", re.IGNORECASE)
        sell_compiled = [re.compile(p, re.IGNORECASE) for p in SELL_PATTERNS]

        for msg in messages:
            try:
                ts = datetime.fromisoformat(msg["timestamp"].replace("Z", "+00:00"))
                if ts < cutoff:
                    continue

                content = msg.get("content", "")
                if not ticker_pattern.search(content):
                    continue

                # Check for sell language
                if any(p.search(content) for p in sell_compiled):
                    result["messages_found"].append({
                        "content": content[:200],
                        "author": msg.get("author", {}).get("username", "unknown"),
                        "timestamp": msg["timestamp"],
                    })
                    result["exit_urgency"] += 40
            except Exception:
                continue

        if result["messages_found"]:
            result["alert"] = f"Analyst mentioned selling {ticker} {len(result['messages_found'])} time(s) recently"

    except Exception as e:
        result["error"] = str(e)[:200]

    return result


def main():
    parser = argparse.ArgumentParser(description="Discord sell signal check")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--since-minutes", type=int, default=30)
    parser.add_argument("--output", default="sell.json")
    args = parser.parse_args()

    result = check_sell_signal(args.ticker, args.since_minutes)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
