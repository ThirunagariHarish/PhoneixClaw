"""Send notifications about trade events via WhatsApp / Telegram / Phoenix API.

Usage:
    python notify.py --event trade_entry --ticker AAPL --message "BUY AAPL @ 185"
    python notify.py --event position_closed --ticker AAPL --message "Closed +3.8%"

Or import directly:
    from notify import send_notification
    send_notification("trade_entry", "AAPL", "BUY AAPL @ 185", config)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [notify] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


def send_notification(
    event_type: str,
    ticker: str,
    message: str,
    config: dict | None = None,
) -> dict:
    """Dispatch a notification through available channels.

    Channels tried in order:
    1. Phoenix API ``POST /api/v2/notifications`` (always)
    2. WhatsApp via ``shared.whatsapp.sender`` (if WHATSAPP_TOKEN set)
    3. Telegram via HTTP (if TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID set)
    """
    config = config or {}
    results: dict = {"event_type": event_type, "ticker": ticker, "channels": []}

    agent_id = config.get("agent_id") or os.getenv("PHOENIX_AGENT_ID", "")
    api_base = config.get("api_base_url") or os.getenv("PHOENIX_API_URL", "http://localhost:8011")

    # 1. Phoenix API notification
    try:
        import httpx
        payload = {
            "agent_id": agent_id,
            "event_type": event_type,
            "ticker": ticker,
            "message": message,
        }
        resp = httpx.post(
            f"{api_base}/api/v2/notifications",
            json=payload,
            timeout=5.0,
            headers={"Content-Type": "application/json"},
        )
        results["channels"].append({"channel": "phoenix_api", "status": resp.status_code})
    except Exception as exc:
        results["channels"].append({"channel": "phoenix_api", "error": str(exc)[:200]})

    # 2. WhatsApp
    whatsapp_token = os.getenv("WHATSAPP_TOKEN")
    whatsapp_to = os.getenv("WHATSAPP_TO_NUMBER")
    if whatsapp_token and whatsapp_to:
        try:
            from shared.whatsapp.sender import send_message
            send_message(whatsapp_to, f"[{event_type}] {ticker}: {message}")
            results["channels"].append({"channel": "whatsapp", "status": "sent"})
        except Exception as exc:
            results["channels"].append({"channel": "whatsapp", "error": str(exc)[:200]})

    # 3. Telegram
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID")
    if tg_token and tg_chat:
        try:
            import httpx
            text = f"*{event_type.upper()}*\n{ticker}: {message}"
            resp = httpx.post(
                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                json={"chat_id": tg_chat, "text": text, "parse_mode": "Markdown"},
                timeout=5.0,
            )
            results["channels"].append({"channel": "telegram", "status": resp.status_code})
        except Exception as exc:
            results["channels"].append({"channel": "telegram", "error": str(exc)[:200]})

    log.info("Notification sent: %s %s via %d channel(s)",
             event_type, ticker, len(results["channels"]))
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="Send trade notification")
    ap.add_argument("--event", required=True, help="Event type (trade_entry, position_closed, etc.)")
    ap.add_argument("--ticker", required=True, help="Ticker symbol")
    ap.add_argument("--message", required=True, help="Notification message")
    ap.add_argument("--config", default="config.json", help="Agent config path")
    args = ap.parse_args()

    config = {}
    if Path(args.config).exists():
        config = json.loads(Path(args.config).read_text())

    result = send_notification(args.event, args.ticker, args.message, config)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
