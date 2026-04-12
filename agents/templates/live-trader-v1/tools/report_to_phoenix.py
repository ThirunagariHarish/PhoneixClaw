"""Report agent activity back to Phoenix API."""

import argparse
import json
from datetime import datetime, timezone

import httpx


async def register_agent(config: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{config['phoenix_api_url']}/api/v2/agents",
            json={
                "name": config.get("agent_name", config["channel_name"]),
                "type": "trading",
                "status": "RUNNING",
                "source": "backtesting",
                "channel_name": config["channel_name"],
                "analyst_name": config.get("analyst_name", ""),
                "config": {
                    "model_type": config.get("model_info", {}).get("model_type", ""),
                    "accuracy": config.get("model_info", {}).get("accuracy", 0),
                },
            },
            headers={"Authorization": f"Bearer {config.get('phoenix_api_key', '')}"},
        )
        return resp.json()


async def report_trade(config: dict, trade: dict):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"{config['phoenix_api_url']}/api/v2/agents/{config['agent_id']}/live-trades",
            json=trade,
            headers={"Authorization": f"Bearer {config.get('phoenix_api_key', '')}"},
        )


async def report_heartbeat(config: dict, status: dict):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"{config['phoenix_api_url']}/api/v2/agents/{config['agent_id']}/heartbeat",
            json={
                "status": status.get("status", "listening"),
                "signals_processed": status.get("signals_processed", 0),
                "trades_today": status.get("trades_today", 0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"Authorization": f"Bearer {config.get('phoenix_api_key', '')}"},
        )


async def report_signal_event(config: dict, event_type: str, data: dict):
    """Post a structured log entry to Phoenix so the Logs tab shows signal activity."""
    api_url = config.get("phoenix_api_url", "http://localhost:8011")
    agent_id = config.get("agent_id", "")
    if not agent_id:
        return
    message = f"[{event_type}] "
    if event_type == "signal_received":
        author = data.get("author", "unknown")
        content = data.get("content", "")[:200]
        message += f"New signal from {author}: {content}"
    elif event_type == "signal_decided":
        ticker = data.get("ticker", "?")
        decision = data.get("decision", "?")
        reason = data.get("reason", "")[:200]
        message += f"{decision} on {ticker}" + (f" — {reason}" if reason else "")
    else:
        message += json.dumps(data, default=str)[:300]

    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"{api_url}/api/v2/agents/{agent_id}/logs",
            json={
                "level": "INFO",
                "source": "live_pipeline",
                "message": message,
                "context": {"event": event_type, **data},
            },
            headers={"Authorization": f"Bearer {config.get('phoenix_api_key', '')}"},
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--action", required=True, choices=["register", "trade", "heartbeat"])
    parser.add_argument("--data", help="JSON file with data to report")
    args = parser.parse_args()

    import asyncio
    with open(args.config) as f:
        config = json.load(f)

    if args.action == "register":
        result = asyncio.run(register_agent(config))
        print(json.dumps(result, indent=2))
    elif args.action == "trade" and args.data:
        with open(args.data) as f:
            trade = json.load(f)
        asyncio.run(report_trade(config, trade))
    elif args.action == "heartbeat":
        asyncio.run(report_heartbeat(config, {}))


if __name__ == "__main__":
    main()
