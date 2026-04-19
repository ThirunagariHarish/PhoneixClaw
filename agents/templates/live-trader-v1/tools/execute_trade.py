"""Execute a trade decision via Robinhood MCP.

Bridges the gap between decision_engine.py (which produces decision.json)
and the Robinhood MCP server (which places orders). Also records the trade
in Phoenix API and spawns a position monitor sub-agent.

Usage:
    python execute_trade.py --decision decision.json --config config.json
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from robinhood_mcp_client import RobinhoodMCPClient  # noqa: E402

from shared.utils.circuit_breaker import CircuitBreaker, CircuitBreakerOpen
from shared.observability.metrics import (
    circuit_breaker_gauge,
    subagent_spawn_counter,
    tool_latency_histogram,
    trade_success_counter,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [execute] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).resolve().parent

robinhood_breaker = CircuitBreaker("robinhood", failure_threshold=3, cooldown_seconds=300)
phoenix_api_breaker = CircuitBreaker("phoenix_api", failure_threshold=3, cooldown_seconds=120)


async def _report_trade_to_phoenix_async(config: dict, trade_data: dict):
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
        async with phoenix_api_breaker:
            resp = httpx.post(url, json=trade_data, headers=headers, timeout=15)
            log.info("Trade recorded in Phoenix: status=%d", resp.status_code)
    except CircuitBreakerOpen as cbe:
        log.error("Phoenix API circuit breaker open: %s", cbe)
    except Exception as e:
        log.error("Failed to record trade: %s", e)


def _report_trade_to_phoenix(config: dict, trade_data: dict):
    """Sync wrapper for async Phoenix API call."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(_report_trade_to_phoenix_async(config, trade_data))


async def _spawn_position_agent_async(config: dict, ticker: str, side: str, entry_price: float, quantity: float) -> dict:
    """Ask Phoenix API to spawn a position monitor sub-agent with retry logic."""
    import httpx
    agent_id = config.get("agent_id", "")
    api_url = config.get("phoenix_api_url", "")
    api_key = config.get("phoenix_api_key", "")
    if not agent_id or not api_url:
        return {}
    url = f"{api_url}/api/v2/agents/{agent_id}/spawn-position-agent"
    headers = {"Authorization": f"Bearer {api_key}"}

    for attempt in range(3):
        try:
            backoff_delay = 2 ** attempt
            if attempt > 0:
                log.info("Retry %d/3 after %ds backoff", attempt + 1, backoff_delay)
                await asyncio.sleep(backoff_delay)

            async with phoenix_api_breaker:
                resp = httpx.post(url, json={
                    "ticker": ticker,
                    "side": side,
                    "entry_price": entry_price,
                    "quantity": quantity,
                }, headers=headers, timeout=30)
                log.info("Position agent spawn request: status=%d", resp.status_code)
                return resp.json() if resp.status_code < 400 else {}
        except CircuitBreakerOpen as cbe:
            log.error("Phoenix API circuit breaker open on spawn: %s", cbe)
            return {}
        except Exception as e:
            log.error("Failed to spawn position agent (attempt %d/3): %s", attempt + 1, e)
            if attempt == 2:
                return {}
    return {}


def _spawn_position_agent(config: dict, ticker: str, side: str, entry_price: float, quantity: float) -> dict:
    """Sync wrapper for async spawn call."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(_spawn_position_agent_async(config, ticker, side, entry_price, quantity))


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
    start_time = time.monotonic()
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

    cfg_allow_rth_override = config.get("allow_execute_outside_regular_session") is True
    env_block_outside_rth = os.getenv("PHOENIX_BLOCK_EXECUTE_OUTSIDE_RTH", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    if env_block_outside_rth and not cfg_allow_rth_override:
        try:
            from shared.utils.market_calendar import get_market_status, is_market_open

            if not is_market_open():
                ms = get_market_status()
                log.info("Outside regular session (%s) — order not sent (use watchlist path).", ms["session"])
                return {
                    "status": "deferred",
                    "reason": "outside_regular_session",
                    "market_status": ms,
                }
        except Exception as exc:
            log.debug("Regular-session gate skipped: %s", exc)

    # Signal deduplication: skip if we already executed this exact signal
    signal_id = decision.get("signal_id") or decision.get("signal", {}).get("message_id", "")
    if signal_id:
        dedup_path = Path("executed_signals.json")
        try:
            executed = json.loads(dedup_path.read_text()) if dedup_path.exists() else []
        except Exception:
            executed = []
        if signal_id in executed:
            log.warning("Signal %s already executed — dedup skip", signal_id)
            return {"status": "skipped", "reason": "duplicate_signal", "signal_id": signal_id}
        executed.append(signal_id)
        # Keep last 200 signal IDs
        dedup_path.write_text(json.dumps(executed[-200:]))
        log.info("Signal %s accepted (dedup check passed)", signal_id)

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

    mcp = RobinhoodMCPClient(config)
    mcp.start()

    correlation_id = decision.get("correlation_id") or signal.get("correlation_id") or os.getenv("CORRELATION_ID")

    try:
        # Login with circuit breaker
        async def _login_with_breaker():
            async with robinhood_breaker:
                return mcp.call("robinhood_login", {})

        async def _get_account_with_breaker():
            async with robinhood_breaker:
                return mcp.call("get_account", {})

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        login_result = loop.run_until_complete(_login_with_breaker())
        if correlation_id:
            log.info("Login: %s", json.dumps(login_result)[:200], extra={"correlation_id": correlation_id})
        else:
            log.info("Login: %s", json.dumps(login_result)[:200])

        # Check buying power before placing order
        account = loop.run_until_complete(_get_account_with_breaker())
        buying_power = float(account.get("buying_power", 0))
        notional = quantity * price if price > 0 else 0
        if correlation_id:
            log.info("Account: buying_power=$%.2f, notional=$%.2f", buying_power, notional, extra={"correlation_id": correlation_id})
        else:
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
        async def _place_order_with_breaker():
            async with robinhood_breaker:
                if trade_type == "option" and execution.get("strike") and execution.get("expiry"):
                    return mcp.call("place_option_order", {
                        "ticker": ticker,
                        "quantity": int(quantity),
                        "side": side,
                        "price": price,
                        "expiry": execution["expiry"],
                        "strike": float(execution["strike"]),
                        "option_type": execution.get("option_type", "call"),
                    })
                else:
                    return mcp.call("smart_limit_order", {
                        "ticker": ticker,
                        "quantity": quantity,
                        "side": side,
                        "buffer_bps": 5.0,
                    })

        order_result = loop.run_until_complete(_place_order_with_breaker())

        if correlation_id:
            log.info("Order result: %s", json.dumps(order_result)[:300], extra={"correlation_id": correlation_id})
        else:
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
            trade_success_counter.labels(status="rejected").inc()
            tool_latency_histogram.labels(tool="execute_trade").observe(time.monotonic() - start_time)
            circuit_breaker_gauge.labels(name="robinhood").set(
                2 if robinhood_breaker.state == "open" else 1 if robinhood_breaker.state == "half_open" else 0
            )
            circuit_breaker_gauge.labels(name="phoenix_api").set(
                2 if phoenix_api_breaker.state == "open" else 1 if phoenix_api_breaker.state == "half_open" else 0
            )
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
        if correlation_id:
            trade_data["metadata"] = {"correlation_id": correlation_id}

        if trade_type == "option":
            trade_data["option_type"] = execution.get("option_type")
            trade_data["strike"] = execution.get("strike")
            trade_data["expiry"] = execution.get("expiry")

        _report_trade_to_phoenix(config, trade_data)

        # Spawn position monitor sub-agent for exit management
        if side == "buy":
            spawn_result = _spawn_position_agent(config, ticker, side, fill_price, quantity)
            if spawn_result and spawn_result.get("session_id"):
                subagent_spawn_counter.inc()
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
        trade_success_counter.labels(status="success").inc()
        tool_latency_histogram.labels(tool="execute_trade").observe(time.monotonic() - start_time)
        circuit_breaker_gauge.labels(name="robinhood").set(
            2 if robinhood_breaker.state == "open" else 1 if robinhood_breaker.state == "half_open" else 0
        )
        circuit_breaker_gauge.labels(name="phoenix_api").set(
            2 if phoenix_api_breaker.state == "open" else 1 if phoenix_api_breaker.state == "half_open" else 0
        )
        return result

    finally:
        mcp.stop()


async def _write_dlq(connector_id: str, payload: dict, error: str) -> None:
    """Write failed signal to dead_letter_messages table."""
    try:
        from sqlalchemy import text

        from shared.db.engine import get_session
        async for session in get_session():
            await session.execute(
                text("INSERT INTO dead_letter_messages (connector_id, payload, error) VALUES (:cid, :payload, :error)"),
                {"cid": connector_id, "payload": json.dumps(payload), "error": error[:500]},
            )
            await session.commit()
            log.warning("DLQ write succeeded for connector %s", connector_id, extra={"correlation_id": payload.get("correlation_id")})
    except Exception as dlq_exc:
        log.error("DLQ write failed: %s", dlq_exc)


def main():
    parser = argparse.ArgumentParser(description="Execute a trade via Robinhood MCP")
    parser.add_argument("--decision", required=True, help="Path to decision.json")
    parser.add_argument("--config", required=True, help="Path to config.json")
    args = parser.parse_args()

    try:
        result = execute(args.decision, args.config)
        print(json.dumps(result, indent=2, default=str))
    except (CircuitBreakerOpen, Exception) as exc:
        log.error("execute_trade failed: %s", exc, exc_info=True)
        connector_id = "unknown"
        decision_dict = {}
        if Path(args.config).exists():
            try:
                cfg = json.loads(Path(args.config).read_text())
                connector_id = cfg.get("connector_id", "unknown")
            except Exception:
                pass
        if Path(args.decision).exists():
            try:
                decision_dict = json.loads(Path(args.decision).read_text())
            except Exception:
                pass
        asyncio.run(_write_dlq(connector_id, decision_dict, str(exc)))
        sys.exit(1)


if __name__ == "__main__":
    main()
