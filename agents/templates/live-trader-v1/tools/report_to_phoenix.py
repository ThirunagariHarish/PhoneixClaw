"""Report agent activity back to Phoenix API."""

import argparse
import json
import logging
from datetime import datetime, timezone

import httpx

_log = logging.getLogger(__name__)


def _auth_headers(config: dict) -> dict[str, str]:
    """Build Authorization header, returning empty dict when no key is set."""
    key = config.get("phoenix_api_key", "").strip()
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}


def _has_api_key(config: dict) -> bool:
    return bool(config.get("phoenix_api_key", "").strip())


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
            headers=_auth_headers(config),
        )
        return resp.json()


async def report_trade(config: dict, trade: dict):
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"{config['phoenix_api_url']}/api/v2/agents/{config['agent_id']}/live-trades",
            json=trade,
            headers=_auth_headers(config),
        )


async def report_heartbeat(config: dict, status: dict):
    if not _has_api_key(config):
        return
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"{config['phoenix_api_url']}/api/v2/agents/{config['agent_id']}/heartbeat",
            json={
                "status": status.get("status", "listening"),
                "signals_processed": status.get("signals_processed", 0),
                "trades_today": status.get("trades_today", 0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers=_auth_headers(config),
        )


async def report_signal(config: dict, signal: dict):
    """POST a trade-signal (watchlist / executed / rejected / paper) to Phoenix.

    Writes to trade_signals table so the Watchlist History tab in the dashboard
    is populated.  The ``action`` / ``decision`` field controls which bucket
    it lands in.  Defaults to 'watchlist' when the agent says WATCHLIST.
    """
    api_url = config.get("phoenix_api_url", "http://localhost:8011")
    agent_id = config.get("agent_id", "")
    if not agent_id:
        _log.warning("report_signal: no agent_id in config, skipping")
        return

    decision = str(signal.get("action") or signal.get("decision") or "watchlist").lower()

    payload = {
        "ticker": signal.get("ticker", ""),
        "decision": decision,
        "direction": signal.get("direction") or signal.get("side") or "",
        "reason": signal.get("reason") or signal.get("rejection_reason") or "",
        "author": signal.get("author", ""),
        "signal_source": signal.get("signal_source", "discord"),
        "source_message_id": signal.get("source_message_id") or signal.get("message_id") or "",
        # R-002: use is-not-None check so confidence=0.0 is preserved, not dropped by 'or'
        "confidence": (
            signal["confidence"] if signal.get("confidence") is not None
            else signal.get("model_confidence")
        ),
        "features": signal.get("features") or {},
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{api_url}/api/v2/agents/{agent_id}/trade-signals",
            json=payload,
            headers=_auth_headers(config),
        )
        if resp.status_code >= 400:
            _log.warning(
                "report_signal POST returned %d: %s",
                resp.status_code, resp.text[:200],
            )


async def report_signal_event(config: dict, event_type: str, data: dict):
    """Post a structured log entry to Phoenix so the Logs tab shows signal activity."""
    api_url = config.get("phoenix_api_url", "http://localhost:8011")
    agent_id = config.get("agent_id", "")
    if not agent_id:
        _log.warning("report_signal_event: no agent_id in config, skipping")
        return
    if not _has_api_key(config):
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
    elif event_type == "pipeline_started":
        redis_ok = data.get("redis_ping", False)
        stream_len = data.get("stream_length", -1)
        stream_key = data.get("stream_key", "?")
        pid = data.get("pid", "?")
        message += (
            f"Pipeline online (PID={pid}). "
            f"Redis={'OK' if redis_ok else 'FAIL'}, "
            f"stream={stream_key}, messages_waiting={stream_len}"
        )
        if data.get("import_errors"):
            message += f", IMPORT ERRORS: {data['import_errors']}"
    else:
        message += json.dumps(data, default=str)[:300]

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{api_url}/api/v2/agents/{agent_id}/logs",
            json={
                "level": "INFO",
                "source": "live_pipeline",
                "message": message,
                "context": {"event": event_type, **data},
            },
            headers=_auth_headers(config),
        )
        if resp.status_code >= 400:
            _log.warning(
                "report_signal_event POST returned %d: %s",
                resp.status_code, resp.text[:200],
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--action", required=True,
                        choices=["register", "trade", "heartbeat", "watchlist", "signal"])
    parser.add_argument("--data", help="JSON string or path to JSON file with data to report")
    args = parser.parse_args()

    import asyncio
    with open(args.config) as f:
        config = json.load(f)

    def _load_data() -> dict:
        if not args.data:
            return {}
        import os
        # R-004: guard requires len >= 3 before indexing [1] and [2]
        _looks_like_path = (
            args.data.startswith("/")
            or args.data.startswith("./")
            or args.data.startswith(".\\\\")  # .\  on Windows
            or (len(args.data) >= 3 and args.data[1] == ":" and args.data[2] in "/\\")
        )
        if _looks_like_path:
            if not os.path.exists(args.data):
                print(json.dumps({"ok": False, "error": f"Data file not found: {args.data}"}))
                raise SystemExit(1)
            with open(args.data) as fh:
                return json.load(fh)
        if os.path.exists(args.data):
            with open(args.data) as fh:
                return json.load(fh)
        return json.loads(args.data)

    if args.action == "register":
        result = asyncio.run(register_agent(config))
        print(json.dumps(result, indent=2))
    elif args.action == "trade":
        # R-003: require --data for --action trade to avoid posting empty trade rows
        trade = _load_data()
        if not trade:
            print(json.dumps({"ok": False, "error": "--data is required for --action trade"}))
            raise SystemExit(1)
        asyncio.run(report_trade(config, trade))
    elif args.action == "heartbeat":
        asyncio.run(report_heartbeat(config, _load_data()))
    elif args.action in ("watchlist", "signal"):
        signal = _load_data()
        # Allow --action watchlist without explicitly setting decision in the data
        if args.action == "watchlist" and "decision" not in signal and "action" not in signal:
            signal["decision"] = "watchlist"
        asyncio.run(report_signal(config, signal))
        print(json.dumps({"ok": True, "action": args.action}))


if __name__ == "__main__":
    main()
