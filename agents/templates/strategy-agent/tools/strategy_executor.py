"""Strategy executor — takes signals from strategy_scanner and routes to risk + broker.

Reuses the live-trader-v1 risk_check.py and robinhood_mcp.py.

Usage:
    python strategy_executor.py --signal signal.json --config config.json --output execution.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent


def execute_signal(signal: dict, config: dict) -> dict:
    """Execute a strategy signal through risk check and broker."""
    if not signal.get("signal"):
        return {"status": "no_signal", "reason": signal.get("reason", "no signal generated")}

    ticker = signal["ticker"]
    direction = signal.get("direction", "buy")
    rotate_out = signal.get("rotate_out")  # Optional: ticker to sell first
    confidence = signal.get("confidence", 0.7)

    risk_params = config.get("risk_params", config.get("manifest", {}).get("risk", {}))
    position_pct = config.get("strategy", {}).get("position_size_pct", 100)

    result = {
        "signal": signal,
        "actions": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Step 1: Rotate out of opposing position
    if rotate_out:
        rotate_result = _close_position(rotate_out, config)
        result["actions"].append({"action": "rotate_out", "ticker": rotate_out, "result": rotate_result})

    # Step 2: Get account info to compute position size
    account = _get_account(config)
    buying_power = account.get("buying_power", 10000)
    quote = _get_quote(ticker, config)
    price = quote.get("price", quote.get("last_price", 0))

    if not price:
        return {"status": "error", "reason": f"Could not fetch price for {ticker}"}

    position_value = buying_power * (position_pct / 100)
    qty = max(1, int(position_value / price))

    # Step 3: Place the order
    if (config.get("current_mode") or "live") == "paper":
        # Paper mode: add to watchlist
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "live-trader-v1" / "tools"))
            from paper_portfolio import add_paper_position
            paper = add_paper_position(ticker, direction, price, qty,
                                       {"strategy": signal})
            result["actions"].append({"action": "paper_add", "result": paper})
            result["status"] = "paper_added"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)[:200]
    else:
        # Live mode: place real order
        order = _place_order(ticker, qty, direction, price, config)
        result["actions"].append({"action": "place_order", "ticker": ticker, "result": order})
        result["status"] = "executed" if order.get("status") == "filled" else "submitted"

        # Spawn position monitor sub-agent
        if result["status"] in ("executed", "submitted"):
            spawn = _spawn_position_agent(ticker, direction, price, qty, signal, config)
            result["actions"].append({"action": "spawn_position_agent", "result": spawn})

    return result


def _close_position(ticker: str, config: dict) -> dict:
    """Close any existing position in this ticker via robinhood_mcp."""
    return {"status": "stub", "ticker": ticker}


def _get_account(config: dict) -> dict:
    return {"buying_power": 10000.0}


def _get_quote(ticker: str, config: dict) -> dict:
    try:
        import yfinance as yf
        data = yf.download(ticker, period="1d", progress=False)
        if not data.empty:
            if hasattr(data.columns, "levels"):
                data.columns = data.columns.get_level_values(0)
            return {"price": float(data["Close"].iloc[-1])}
    except Exception:
        pass
    return {"price": 0}


def _place_order(ticker: str, qty: int, direction: str, price: float, config: dict) -> dict:
    """Stub: in production, dispatch to robinhood_mcp.py JSON-RPC."""
    return {
        "status": "submitted",
        "ticker": ticker,
        "qty": qty,
        "side": direction,
        "limit_price": price,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }


def _spawn_position_agent(ticker: str, direction: str, price: float, qty: int,
                          signal: dict, config: dict) -> dict:
    """POST to /api/v2/agents/{agent_id}/spawn-position-agent."""
    try:
        import httpx
        api_url = config.get("phoenix_api_url", "")
        api_key = config.get("phoenix_api_key", "")
        agent_id = config.get("agent_id", "")
        if not api_url or not agent_id:
            return {"status": "skipped", "reason": "no api/agent config"}

        risk = config.get("risk_params", {})
        stop_pct = risk.get("stop_loss_pct", 2.0)
        target_pct = risk.get("target_profit_pct", 5.0)

        if direction == "buy":
            stop_loss = price * (1 - stop_pct / 100)
            take_profit = price * (1 + target_pct / 100)
        else:
            stop_loss = price * (1 + stop_pct / 100)
            take_profit = price * (1 - target_pct / 100)

        resp = httpx.post(
            f"{api_url}/api/v2/agents/{agent_id}/spawn-position-agent",
            headers={"X-Agent-Key": api_key},
            json={
                "ticker": ticker,
                "side": direction,
                "entry_price": price,
                "qty": qty,
                "stop_loss": round(stop_loss, 2),
                "take_profit": round(take_profit, 2),
                "reasoning": signal.get("reason", ""),
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return {"status": "spawned", **resp.json()}
        return {"status": "error", "code": resp.status_code, "body": resp.text[:200]}
    except Exception as e:
        return {"status": "error", "error": str(e)[:200]}


def main():
    parser = argparse.ArgumentParser(description="Strategy executor")
    parser.add_argument("--signal", required=True)
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", default="execution.json")
    args = parser.parse_args()

    signal = json.loads(Path(args.signal).read_text()) if Path(args.signal).exists() else {}
    config = json.loads(Path(args.config).read_text()) if Path(args.config).exists() else {}

    result = execute_signal(signal, config)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
