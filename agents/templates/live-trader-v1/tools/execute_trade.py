"""Execute a trade decision via Robinhood MCP.

Bridges the gap between decision_engine.py (which produces decision.json)
and the Robinhood MCP server (which places orders). Also records the trade
in Phoenix API and spawns a position monitor sub-agent.

Usage:
    python execute_trade.py --decision decision.json --config config.json
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [execute] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).resolve().parent


class MCPClient:
    """Communicate with robinhood_mcp.py via stdio JSON-RPC."""

    def __init__(self, config: dict):
        self.config = config
        self.proc = None
        self._request_id = 0

    def start(self):
        import os
        import threading
        env = os.environ.copy()
        creds = self.config.get("robinhood_credentials", self.config.get("robinhood", {}))
        if isinstance(creds, dict):
            env["RH_USERNAME"] = creds.get("username", "")
            env["RH_PASSWORD"] = creds.get("password", "")
            env["RH_TOTP_SECRET"] = creds.get("totp_secret", "")
        if self.config.get("paper_mode"):
            env["PAPER_MODE"] = "true"
        self.proc = subprocess.Popen(
            [sys.executable, str(TOOLS_DIR / "robinhood_mcp.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        # Drain stderr in a daemon thread to prevent pipe deadlock
        def _drain_stderr():
            for line in self.proc.stderr:
                log.debug("[mcp-stderr] %s", line.rstrip())
        t = threading.Thread(target=_drain_stderr, daemon=True)
        t.start()
        log.info("MCP server started (pid=%d)", self.proc.pid)

    def call(self, tool_name: str, arguments: dict, timeout: int = 60) -> dict:
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        self.proc.stdin.write(json.dumps(request) + "\n")
        self.proc.stdin.flush()

        start = time.time()
        while time.time() - start < timeout:
            line = self.proc.stdout.readline()
            if not line:
                break
            try:
                resp = json.loads(line.strip())
                if resp.get("id") == self._request_id:
                    if "error" in resp:
                        return {"error": resp["error"]}
                    result = resp.get("result", {})
                    content = result.get("content", [{}])
                    if isinstance(content, list) and content:
                        text = content[0].get("text", "{}")
                        return json.loads(text) if text.startswith("{") else {"raw": text}
                    return result
            except (json.JSONDecodeError, KeyError):
                continue
        return {"error": "timeout"}

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=5)


def _report_trade_to_phoenix(config: dict, trade_data: dict):
    """POST the trade to Phoenix API so it appears in the dashboard."""
    import httpx
    agent_id = config.get("agent_id", "")
    api_url = config.get("phoenix_api_url", "")
    api_key = config.get("phoenix_api_key", "")
    if not agent_id or not api_url:
        log.warning("Missing agent_id or phoenix_api_url, skipping trade recording")
        return
    url = f"{api_url}/api/v2/agents/{agent_id}/live-trades"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = httpx.post(url, json=trade_data, headers=headers, timeout=15)
        log.info("Trade recorded in Phoenix: status=%d", resp.status_code)
    except Exception as e:
        log.error("Failed to record trade: %s", e)


def _spawn_position_agent(config: dict, ticker: str, side: str, entry_price: float, quantity: float) -> dict:
    """Ask Phoenix API to spawn a position monitor sub-agent."""
    import httpx
    agent_id = config.get("agent_id", "")
    api_url = config.get("phoenix_api_url", "")
    api_key = config.get("phoenix_api_key", "")
    if not agent_id or not api_url:
        return {}
    url = f"{api_url}/api/v2/agents/{agent_id}/spawn-position-agent"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = httpx.post(url, json={
            "ticker": ticker,
            "side": side,
            "entry_price": entry_price,
            "quantity": quantity,
        }, headers=headers, timeout=30)
        log.info("Position agent spawn request: status=%d", resp.status_code)
        return resp.json() if resp.status_code < 400 else {}
    except Exception as e:
        log.error("Failed to spawn position agent: %s", e)
        return {}


def _register_position(ticker: str, side: str, entry_price: float, quantity: float,
                       order_id: str, spawn_result: dict):
    """Maintain position_registry.json so the primary agent can route sell signals."""
    registry_path = Path("position_registry.json")
    try:
        registry = json.loads(registry_path.read_text()) if registry_path.exists() else {}
    except Exception:
        registry = {}
    registry[ticker] = {
        "side": side,
        "entry_price": entry_price,
        "quantity": quantity,
        "order_id": order_id,
        "session_id": spawn_result.get("session_id", ""),
        "sub_agent_id": spawn_result.get("agent_id", ""),
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    registry_path.write_text(json.dumps(registry, indent=2, default=str))
    log.info("Position registered: %s -> %s", ticker, registry[ticker].get("session_id", "local"))


def execute(decision_path: str, config_path: str):
    if isinstance(decision_path, dict):
        decision = decision_path
    else:
        with open(decision_path) as f:
            decision = json.load(f)
    with open(config_path) as f:
        config = json.load(f)

    verdict = decision.get("decision", "").upper()
    if verdict not in ("EXECUTE", "PAPER"):
        log.info("Decision is %s — nothing to execute", verdict)
        return {"status": "skipped", "reason": verdict}

    execution = decision.get("execution", {})
    # decision_engine uses "parsed_signal", live_pipeline uses "signal"
    signal = decision.get("signal", decision.get("parsed_signal", {}))

    ticker = execution.get("ticker") or signal.get("ticker", "")
    # decision_engine outputs "direction", execute_trade expects "side"
    side = execution.get("side") or execution.get("direction") or signal.get("direction", "buy")
    quantity = float(execution.get("quantity") or execution.get("shares") or execution.get("position_size_pct") or 1)
    # decision_engine outputs "entry_price" and "signal_price", not "price"
    price = float(execution.get("price") or execution.get("entry_price") or execution.get("signal_price") or signal.get("signal_price") or 0)
    trade_type = signal.get("trade_type") or execution.get("trade_type") or ("option" if execution.get("option_type") else "stock")
    is_paper = verdict == "PAPER" or config.get("paper_mode", False)

    if not ticker:
        log.error("No ticker in decision")
        return {"status": "error", "reason": "no_ticker"}

    log.info("Executing %s: %s %s %.0f @ $%.2f (paper=%s)",
             trade_type, side, ticker, quantity, price, is_paper)

    if is_paper:
        config["paper_mode"] = True

    mcp = MCPClient(config)
    mcp.start()

    try:
        # Login
        login_result = mcp.call("robinhood_login", {})
        log.info("Login: %s", json.dumps(login_result)[:200])

        # Check buying power before placing order
        account = mcp.call("get_account", {})
        buying_power = float(account.get("buying_power", 0))
        notional = quantity * price if price > 0 else 0
        log.info("Account: buying_power=$%.2f, notional=$%.2f", buying_power, notional)

        # Build reasoning and signal_raw from the decision structure
        reasoning_list = decision.get("reasoning", [])
        reasoning_text = " | ".join(reasoning_list) if isinstance(reasoning_list, list) else str(reasoning_list)
        signal_raw = signal.get("content") or signal.get("raw_message") or decision.get("signal_raw", "")
        model_conf = (decision.get("confidence") or
                      decision.get("model_prediction", {}).get("confidence") or 0)
        # Build decision trail for audit
        decision_trail = {
            "steps": decision.get("steps", []),
            "reasoning": reasoning_list,
            "risk_check": decision.get("risk_check"),
            "ta_summary": decision.get("ta_summary"),
            "model_prediction": decision.get("model_prediction"),
            "execution_params": execution,
        }

        if side == "buy" and notional > 0 and notional > buying_power:
            log.warning("Insufficient buying power: need $%.2f, have $%.2f", notional, buying_power)
            _report_trade_to_phoenix(config, {
                "ticker": ticker,
                "side": side,
                "entry_price": price,
                "quantity": quantity,
                "model_confidence": model_conf,
                "reasoning": f"Rejected: insufficient buying power (need ${notional:.0f}, have ${buying_power:.0f})",
                "signal_raw": signal_raw,
                "decision_status": "rejected",
                "rejection_reason": "insufficient_buying_power",
                "status": "rejected",
                "decision_trail": decision_trail,
            })
            return {"status": "rejected", "reason": "insufficient_buying_power"}

        # Place order via smart_limit_order (has NBBO pegging + buying power check)
        if trade_type == "option" and execution.get("strike") and execution.get("expiry"):
            order_result = mcp.call("place_option_order", {
                "ticker": ticker,
                "quantity": int(quantity),
                "side": side,
                "price": price,
                "expiry": execution["expiry"],
                "strike": float(execution["strike"]),
                "option_type": execution.get("option_type", "call"),
            })
        else:
            order_result = mcp.call("smart_limit_order", {
                "ticker": ticker,
                "quantity": quantity,
                "side": side,
                "buffer_bps": 5.0,
            })

        log.info("Order result: %s", json.dumps(order_result)[:300])

        order_id = order_result.get("order_id", "")
        fill_price = float(order_result.get("fill_price", price) or price)
        state = order_result.get("state", order_result.get("status", "unknown"))

        if state in ("rejected", "error", "timed_out"):
            _report_trade_to_phoenix(config, {
                "ticker": ticker,
                "side": side,
                "entry_price": price,
                "quantity": quantity,
                "model_confidence": model_conf,
                "reasoning": f"Order rejected by broker: {order_result.get('reason', state)}",
                "signal_raw": signal_raw,
                "decision_status": "rejected",
                "rejection_reason": order_result.get("reason", state),
                "status": "rejected",
                "decision_trail": decision_trail,
            })
            return {"status": "rejected", "reason": order_result.get("reason", state)}

        # Record successful trade in Phoenix
        pattern_matches = (decision.get("patterns") or
                           decision.get("pattern_matches") or
                           decision.get("model_prediction", {}).get("pattern_matches") or [])
        trade_data = {
            "ticker": ticker,
            "side": side,
            "entry_price": fill_price,
            "quantity": quantity,
            "model_confidence": model_conf,
            "pattern_matches": pattern_matches,
            "reasoning": reasoning_text,
            "signal_raw": signal_raw,
            "broker_order_id": order_id,
            "decision_status": "accepted",
            "status": "open",
            "decision_trail": decision_trail,
        }
        if trade_type == "option":
            trade_data["option_type"] = execution.get("option_type")
            trade_data["strike"] = execution.get("strike")
            trade_data["expiry"] = execution.get("expiry")

        _report_trade_to_phoenix(config, trade_data)

        # Spawn position monitor sub-agent for exit management
        if side == "buy":
            spawn_result = _spawn_position_agent(config, ticker, side, fill_price, quantity)
            _register_position(ticker, side, fill_price, quantity, order_id, spawn_result)

        # Write execution result for the agent to read
        result = {
            "status": "executed",
            "ticker": ticker,
            "side": side,
            "quantity": quantity,
            "fill_price": fill_price,
            "order_id": order_id,
            "broker_state": state,
            "paper_mode": is_paper,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if isinstance(decision_path, str):
            result_path = Path(decision_path).parent / "execution_result.json"
        else:
            result_path = Path("execution_result.json")
        result_path.write_text(json.dumps(result, indent=2))
        log.info("Trade executed: %s %s %.0f @ $%.2f", side, ticker, quantity, fill_price)
        return result

    finally:
        mcp.stop()


def main():
    parser = argparse.ArgumentParser(description="Execute a trade via Robinhood MCP")
    parser.add_argument("--decision", required=True, help="Path to decision.json")
    parser.add_argument("--config", required=True, help="Path to config.json")
    args = parser.parse_args()

    result = execute(args.decision, args.config)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
