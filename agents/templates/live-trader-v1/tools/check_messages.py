"""Poll Phoenix API for new channel messages.

The agent calls this every ~5 seconds. It hits the existing
GET /api/v2/agents/{agent_id}/channel-messages endpoint (which reads from
PostgreSQL, populated by the ingestion service), deduplicates against
already-processed message IDs, and prints new messages as JSON to stdout.

Usage:
    python3 tools/check_messages.py --config config.json

Output (stdout): JSON with new unprocessed messages.
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
    format="%(asctime)s [check_messages] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

LAST_CHECK_FILE = Path("last_check.json")
PROCESSED_IDS_FILE = Path("processed_ids.json")
MAX_PROCESSED_IDS = 500


def _load_last_check() -> str | None:
    if LAST_CHECK_FILE.exists():
        try:
            data = json.loads(LAST_CHECK_FILE.read_text())
            return data.get("since")
        except Exception:
            pass
    return None


def _save_last_check(since: str) -> None:
    LAST_CHECK_FILE.write_text(json.dumps({
        "since": since,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }))


def _load_processed_ids() -> set[str]:
    if PROCESSED_IDS_FILE.exists():
        try:
            return set(json.loads(PROCESSED_IDS_FILE.read_text()))
        except Exception:
            pass
    return set()


def _save_processed_ids(ids: set[str]) -> None:
    trimmed = sorted(ids)[-MAX_PROCESSED_IDS:]
    PROCESSED_IDS_FILE.write_text(json.dumps(trimmed))


def check(config_path: str) -> dict:
    with open(config_path) as f:
        config = json.load(f)

    agent_id = config.get("agent_id", "")
    api_url = config.get("phoenix_api_url", "").rstrip("/")
    api_key = config.get("phoenix_api_key", "")

    if not agent_id or not api_url:
        return {"error": "Missing agent_id or phoenix_api_url in config", "count": 0, "new_messages": []}

    since = _load_last_check()
    params: dict = {"limit": 50}
    if since:
        # Subtract a 120-second lookback buffer so messages that were
        # POSTED slightly before this cursor but INGESTED after it are
        # not permanently missed.  The processed_ids dedup layer prevents
        # the agent from re-acting on messages it already handled.
        try:
            from datetime import timedelta
            since_dt = datetime.fromisoformat(since)
            buffered_since = (since_dt - timedelta(seconds=120)).isoformat()
            params["since"] = buffered_since
        except Exception:
            params["since"] = since

    url = f"{api_url}/api/v2/agents/{agent_id}/channel-messages"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    try:
        resp = httpx.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code >= 400:
            log.warning("API returned %d: %s", resp.status_code, resp.text[:200])
            return {"error": f"API error {resp.status_code}", "count": 0, "new_messages": []}
        data = resp.json()
    except Exception as exc:
        log.error("Failed to fetch messages: %s", exc)
        return {"error": str(exc)[:200], "count": 0, "new_messages": []}

    # has_connectors=False means no Discord connector is linked to this agent.
    # Guard on the connector state alone — do NOT also require messages to be empty,
    # because a cached/stale message list must not suppress the warning (R-001 fix).
    # Do NOT advance the `since` cursor here: if a connector is added later, we want
    # to backfill messages from this point forward rather than skipping them (R-005 fix).
    if not data.get("has_connectors", True):
        log.error(
            "NO CONNECTOR LINKED: This agent has no Discord connector attached. "
            "Go to Dashboard → Agent → Settings and link a Discord connector. "
            "Signals CANNOT be received until a connector is configured."
        )
        return {
            "count": 0,
            "new_messages": [],
            "warning": "no_connector_linked",
            "warning_message": (
                "No Discord connector is linked to this agent. "
                "Link one in the dashboard to start receiving signals."
            ),
        }

    all_messages = data.get("messages", [])
    processed_ids = _load_processed_ids()

    new_messages = []
    for msg in all_messages:
        msg_key = msg.get("platform_message_id") or msg.get("id", "")
        if not msg_key or msg_key in processed_ids:
            continue
        new_messages.append(msg)
        processed_ids.add(msg_key)

    # Only advance the cursor when we successfully polled with a live connector.
    now_iso = datetime.now(timezone.utc).isoformat()
    _save_last_check(now_iso)

    if new_messages:
        _save_processed_ids(processed_ids)

    new_messages.sort(key=lambda m: m.get("posted_at", ""))

    return {
        "new_messages": new_messages,
        "count": len(new_messages),
        "total_checked": len(all_messages),
        "since": since or "first_check",
    }


def main():
    parser = argparse.ArgumentParser(description="Poll Phoenix API for new channel messages")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    args = parser.parse_args()

    result = check(args.config)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
