"""Inter-agent communication tool for live trading agents.

Allows an agent to send/receive knowledge to/from other agents via the
Phoenix /api/v2/agent-messages endpoint.

Knowledge intents:
  market_briefing, position_update, risk_alert, exit_signal,
  strategy_insight, headline_alert, unusual_flow, sell_signal,
  morning_research, pattern_alert, market_regime

Usage:
    # Send knowledge to a specific agent
    python agent_comms.py --send <agent_id> --intent strategy_insight --data data.json

    # Broadcast knowledge to all agents
    python agent_comms.py --broadcast --intent market_briefing --data briefing.json

    # Get pending messages for this agent
    python agent_comms.py --get-pending --output messages.json

    # Mark message as read
    python agent_comms.py --mark-read <message_id>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _get_api_config() -> dict:
    """Load Phoenix API config from local config.json."""
    config_path = Path("config.json")
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
            return {
                "url": cfg.get("phoenix_api_url") or os.getenv("PHOENIX_API_URL", "http://localhost:8011"),
                "key": cfg.get("phoenix_api_key", "") or os.getenv("PHOENIX_API_KEY", ""),
                "agent_id": cfg.get("agent_id", "") or os.getenv("AGENT_ID", ""),
            }
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "url": os.getenv("PHOENIX_API_URL", "http://localhost:8011"),
        "key": os.getenv("PHOENIX_API_KEY", ""),
        "agent_id": os.getenv("AGENT_ID", ""),
    }


def send_knowledge(to_agent_id: str, intent: str, data: dict, body: str = "") -> dict:
    """Send a knowledge message to a specific agent."""
    try:
        import httpx
        cfg = _get_api_config()
        if not cfg["agent_id"]:
            return {"error": "agent_id not configured"}

        resp = httpx.post(
            f"{cfg['url']}/api/v2/agent-messages",
            headers={"X-Agent-Key": cfg["key"]},
            json={
                "from_agent_id": cfg["agent_id"],
                "to_agent_id": to_agent_id,
                "pattern": "request-response",
                "intent": intent,
                "data": data,
                "body": body,
                "topic": intent,
            },
            timeout=10,
        )
        if resp.status_code == 201:
            return {"status": "sent", "message_id": resp.json().get("id", "")}
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)[:200]}


def broadcast_knowledge(intent: str, data: dict, body: str = "") -> dict:
    """Broadcast knowledge to all agents."""
    try:
        import httpx
        cfg = _get_api_config()
        if not cfg["agent_id"]:
            return {"error": "agent_id not configured"}

        resp = httpx.post(
            f"{cfg['url']}/api/v2/agent-messages",
            headers={"X-Agent-Key": cfg["key"]},
            json={
                "from_agent_id": cfg["agent_id"],
                "to_agent_id": None,  # Broadcast
                "pattern": "broadcast",
                "intent": intent,
                "data": data,
                "body": body,
                "topic": intent,
            },
            timeout=10,
        )
        if resp.status_code == 201:
            return {"status": "broadcast", "message_id": resp.json().get("id", "")}
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)[:200]}


def get_pending_messages(limit: int = 50) -> list[dict]:
    """Get pending messages addressed to this agent (or broadcast)."""
    try:
        import httpx
        cfg = _get_api_config()
        if not cfg["agent_id"]:
            return []

        resp = httpx.get(
            f"{cfg['url']}/api/v2/agent-messages",
            headers={"X-Agent-Key": cfg["key"]},
            params={
                "to_agent_id": cfg["agent_id"],
                "status": "pending",
                "limit": limit,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"  [agent_comms] Get pending failed: {e}", file=sys.stderr)
    return []


def mark_read(message_id: str) -> dict:
    """Mark a message as consumed."""
    try:
        import httpx
        cfg = _get_api_config()
        resp = httpx.patch(
            f"{cfg['url']}/api/v2/agent-messages/{message_id}/mark-read",
            headers={"X-Agent-Key": cfg["key"]},
            timeout=10,
        )
        if resp.status_code == 200:
            return {"status": "read", "message_id": message_id}
        return {"error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"error": str(e)[:200]}


def main():
    parser = argparse.ArgumentParser(description="Inter-agent communication tool")
    parser.add_argument("--send", metavar="AGENT_ID", help="Send to specific agent")
    parser.add_argument("--broadcast", action="store_true", help="Broadcast to all agents")
    parser.add_argument("--get-pending", action="store_true", help="Get pending messages")
    parser.add_argument("--mark-read", metavar="MSG_ID", help="Mark message as read")
    parser.add_argument("--intent", help="Knowledge intent")
    parser.add_argument("--data", help="JSON data file path")
    parser.add_argument("--body", default="", help="Optional message body")
    parser.add_argument("--output", default=None, help="Output file (for --get-pending)")
    args = parser.parse_args()

    if args.send:
        if not args.intent or not args.data:
            print("Error: --intent and --data required for --send", file=sys.stderr)
            sys.exit(1)
        data = json.loads(Path(args.data).read_text())
        result = send_knowledge(args.send, args.intent, data, args.body)
        print(json.dumps(result, indent=2))
    elif args.broadcast:
        if not args.intent or not args.data:
            print("Error: --intent and --data required for --broadcast", file=sys.stderr)
            sys.exit(1)
        data = json.loads(Path(args.data).read_text())
        result = broadcast_knowledge(args.intent, data, args.body)
        print(json.dumps(result, indent=2))
    elif args.get_pending:
        messages = get_pending_messages()
        if args.output:
            Path(args.output).write_text(json.dumps(messages, indent=2, default=str))
        print(json.dumps({
            "count": len(messages),
            "messages": messages,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }, indent=2, default=str))
    elif args.mark_read:
        result = mark_read(args.mark_read)
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
