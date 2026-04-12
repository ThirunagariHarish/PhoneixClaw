"""Send notifications to the user via Phoenix API.

Referenced by supervisor CLAUDE.md Phase 5 reporting.
Supports WhatsApp, Telegram, and dashboard notification channels.

Usage:
    python notify_user.py --event supervisor_report --data summary.json
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [notify] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


def _load_config() -> dict:
    cfg_path = Path("config.json")
    if cfg_path.exists():
        return json.loads(cfg_path.read_text())
    return {}


def send_notification(event: str, data: dict | str, config: dict | None = None) -> dict:
    config = config or _load_config()
    agent_id = config.get("agent_id", "")
    api_url = config.get("phoenix_api_url", os.getenv("PHOENIX_API_URL", ""))
    api_key = config.get("phoenix_api_key", os.getenv("PHOENIX_API_KEY", ""))

    if not api_url:
        log.warning("No phoenix_api_url configured, skipping notification")
        return {"status": "skipped", "reason": "no_api_url"}

    if isinstance(data, str):
        data_path = Path(data)
        if data_path.exists():
            data = json.loads(data_path.read_text())
        else:
            data = {"message": data}

    payload = {
        "event": event,
        "agent_id": agent_id,
        "data": data,
    }

    url = f"{api_url}/api/v2/notifications"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=15)
        log.info("Notification sent: event=%s status=%d", event, resp.status_code)
        return {"status": "sent", "http_status": resp.status_code}
    except Exception as e:
        log.error("Failed to send notification: %s", e)
        # Fall back to writing to a local file so the dashboard can pick it up
        notif_path = Path(f"notification_{event}.json")
        notif_path.write_text(json.dumps(payload, indent=2, default=str))
        return {"status": "fallback_file", "path": str(notif_path), "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="Send user notification via Phoenix API")
    parser.add_argument("--event", required=True, help="Event type (e.g., supervisor_report)")
    parser.add_argument("--data", required=True, help="Path to JSON data file or inline message")
    args = parser.parse_args()

    result = send_notification(args.event, args.data)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
