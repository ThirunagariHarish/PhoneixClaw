"""Exit decision orchestrator for position monitoring.

Combines TA (15+ indicators), MAG-7 correlation, options flow,
macro signals, analyst sell signals, and risk levels into a single
HOLD/PARTIAL_EXIT/FULL_EXIT decision with reasoning.

Usage:
    python exit_decision.py --position-id POS123 --output decision.json
    python exit_decision.py --position-id POS123 --execute --pct 50
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent


def _run_tool(script: str, args: list[str], timeout: int = 60) -> dict:
    """Run a sibling tool and return its JSON output."""
    try:
        cmd = [sys.executable, str(TOOLS_DIR / script)] + args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        pass
    return {}


def get_current_price(ticker: str) -> float | None:
    try:
        import yfinance as yf
        data = yf.download(ticker, period="1d", interval="1m", progress=False)
        if data.empty:
            return None
        if hasattr(data.columns, "levels"):
            data.columns = data.columns.get_level_values(0)
        return float(data["Close"].iloc[-1])
    except Exception:
        return None


def make_exit_decision(position: dict, config: dict) -> dict:
    ticker = position.get("ticker", "")
    side = position.get("side", "buy")
    entry_price = float(position.get("entry_price", 0))
    qty = position.get("qty", 0)
    stop_loss = position.get("stop_loss")
    take_profit = position.get("take_profit")

    current_price = get_current_price(ticker)
    if current_price is None:
        return {
            "action": "HOLD",
            "urgency": 0,
            "reasoning": "Could not fetch current price",
            "ticker": ticker,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Compute P&L
    if side == "buy":
        pnl_pct = (current_price - entry_price) / entry_price * 100
    else:
        pnl_pct = (entry_price - current_price) / entry_price * 100

    # Pass config to TA check for weight overrides
    config_path = Path("config.json")
    ta_args = ["--ticker", ticker, "--side", side, "--output", "/tmp/ta.json"]
    if config_path.exists():
        ta_args.extend(["--config", str(config_path)])

    # Run TA check (15+ indicators)
    ta = _run_tool("ta_check.py", ta_args)
    ta_urgency = ta.get("exit_urgency", 0)

    # Run MAG-7 + cross-asset correlation (+ sector breakdown when ticker known)
    mag7 = _run_tool(
        "mag7_correlation.py",
        ["--ticker", ticker, "--side", side, "--output", "/tmp/mag7.json"],
    )
    mag7_urgency = mag7.get("exit_urgency", 0)

    # Run options flow check (Unusual Whales)
    options_flow = _run_tool("options_flow_check.py",
                             ["--ticker", ticker, "--side", side, "--output", "/tmp/flow.json"])
    options_urgency = options_flow.get("exit_urgency", 0)

    # Run macro check (FRED)
    macro = _run_tool("macro_check.py", ["--side", side, "--output", "/tmp/macro.json"])
    macro_urgency = macro.get("exit_urgency", 0)

    # Run IBKR data check (optional — degrades gracefully)
    ibkr_args = ["--ticker", ticker, "--side", side, "--output", "/tmp/ibkr.json"]
    option_data = position.get("option_contract")
    if option_data:
        ibkr_args.extend(["--option-contract", json.dumps(option_data)])
    elif position.get("strike") and position.get("expiry"):
        oc = {"strike": position["strike"], "expiry": str(position["expiry"]),
              "right": "C" if position.get("option_type", "call").lower() == "call" else "P"}
        ibkr_args.extend(["--option-contract", json.dumps(oc)])
    ibkr = _run_tool("ibkr_data_check.py", ibkr_args, timeout=30)
    ibkr_urgency = ibkr.get("exit_urgency", 0)

    # Check local sell_signal.json (fast, written by primary agent's sell-routing)
    discord_urgency = 0
    discord = {}
    sell_signal_path = Path(f"positions/{ticker}/sell_signal.json")
    if not sell_signal_path.exists():
        sell_signal_path = Path("sell_signal.json")
    if sell_signal_path.exists():
        try:
            sell_data = json.loads(sell_signal_path.read_text())
            discord = {"alert": f"Analyst sell signal: {sell_data.get('content', '')[:100]}"}
            discord_urgency = 40
        except Exception:
            pass
    if discord_urgency == 0:
        discord = _run_tool("discord_sell_signal.py",
                            ["--ticker", ticker, "--since-minutes", "30", "--output", "/tmp/sell.json"])
        discord_urgency = discord.get("exit_urgency", 0)

    # Risk-level urgency
    risk_urgency = 0
    risk_reasons = []
    risk_params = config.get("risk", config.get("risk_params", {}))
    stop_loss_pct = risk_params.get("stop_loss_pct", 2.0)
    take_profit_pct = risk_params.get("target_profit_pct", 5.0)

    # Hit stop loss
    hit_stop = False
    if stop_loss:
        if (side == "buy" and current_price <= stop_loss) or \
           (side == "sell" and current_price >= stop_loss):
            hit_stop = True
            risk_urgency += 100
            risk_reasons.append(f"Stop loss hit at ${stop_loss}")
    elif pnl_pct <= -stop_loss_pct:
        hit_stop = True
        risk_urgency += 100
        risk_reasons.append(f"P&L {pnl_pct:.2f}% exceeded -{stop_loss_pct}%")

    # Take profit
    hit_target = False
    if take_profit:
        if (side == "buy" and current_price >= take_profit) or \
           (side == "sell" and current_price <= take_profit):
            hit_target = True
            risk_urgency += 30
            risk_reasons.append(f"Take profit hit at ${take_profit}")
    elif pnl_pct >= take_profit_pct:
        hit_target = True
        risk_urgency += 30
        risk_reasons.append(f"P&L {pnl_pct:.2f}% reached {take_profit_pct}% target")

    # Approaching stop loss (>70% of distance)
    if not hit_stop and pnl_pct < 0 and stop_loss_pct > 0 and abs(pnl_pct) > stop_loss_pct * 0.7:
        risk_urgency += 25
        risk_reasons.append(f"Approaching stop loss ({pnl_pct:.2f}% of -{stop_loss_pct}%)")

    # Analyst behavioral exit probability (from analyst_profiles / spawn payload)
    analyst_exit_prediction: dict = {}
    analyst_urgency = 0
    prof = position.get("analyst_exit_profile") or {}
    if prof:
        try:
            from shared.utils.analyst_exit_predictor import predict_analyst_exit

            analyst_exit_prediction = predict_analyst_exit(prof, position, current_price)
            p = int(analyst_exit_prediction.get("probability", 0))
            if p > 70:
                analyst_urgency = 20
            elif p > 50:
                analyst_urgency = 10
        except Exception:
            pass

    # Total urgency (capped at 100)
    total_urgency = min(
        ta_urgency + mag7_urgency + options_urgency + macro_urgency
        + ibkr_urgency + discord_urgency + risk_urgency + analyst_urgency,
        100
    )

    # Decide action
    if hit_stop or total_urgency >= 80:
        action = "FULL_EXIT"
        suggested_pct = 100
    elif total_urgency >= 50:
        action = "PARTIAL_EXIT"
        suggested_pct = 50
    else:
        action = "HOLD"
        suggested_pct = 0

    # Combine reasoning
    reasons = []
    if hit_stop:
        reasons.append("STOP LOSS HIT")
    if hit_target:
        reasons.append("TAKE PROFIT HIT")
    for sig_name, sig_val in ta.get("signals", {}).items():
        reasons.append(f"TA/{sig_name}: {sig_val}")
    if mag7.get("alert"):
        reasons.append(f"MAG-7: {mag7['alert']}")
    for sig_name, sig_val in options_flow.get("signals", {}).items():
        if "alert" in sig_name or "sweep" in sig_name:
            reasons.append(f"Options: {sig_name}={sig_val}")
    for sig_name, sig_val in macro.get("signals", {}).items():
        if "alert" in sig_name or "spike" in sig_name:
            reasons.append(f"Macro: {sig_name}={sig_val}")
    for sig_name, sig_val in ibkr.get("signals", {}).items():
        if "alert" in sig_name:
            reasons.append(f"IBKR: {sig_name}={sig_val}")
    if discord.get("alert"):
        reasons.append(f"Discord: {discord['alert']}")
    reasons.extend(risk_reasons)
    if analyst_exit_prediction:
        for r in analyst_exit_prediction.get("reasons", [])[:5]:
            reasons.append(f"Analyst model: {r}")

    return {
        "action": action,
        "urgency": total_urgency,
        "suggested_exit_pct": suggested_pct,
        "reasoning": "; ".join(reasons) if reasons else f"Position healthy (urgency {total_urgency}/100)",
        "ticker": ticker,
        "side": side,
        "entry_price": entry_price,
        "current_price": current_price,
        "pnl_pct": round(pnl_pct, 2),
        "qty": qty,
        "analyst_exit_prediction": analyst_exit_prediction,
        "signals": {
            "ta": ta_urgency,
            "mag7": mag7_urgency,
            "options_flow": options_urgency,
            "macro": macro_urgency,
            "ibkr": ibkr_urgency,
            "discord": discord_urgency,
            "risk": risk_urgency,
            "analyst_model": analyst_urgency,
        },
        "ta_indicators": ta.get("indicators", {}),
        "ta_signals": ta.get("signals", {}),
        "options_flow_signals": options_flow.get("signals", {}),
        "macro_signals": macro.get("signals", {}),
        "ibkr_signals": ibkr.get("signals", {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def execute_exit(position: dict, exit_pct: int, decision: dict) -> dict:
    """Execute the exit via Robinhood MCP."""
    ticker = position.get("ticker", "")
    qty = position.get("qty", 0)
    qty_to_exit = max(1, int(qty * exit_pct / 100))

    try:
        rh_path = TOOLS_DIR / "robinhood_mcp.py"
        if not rh_path.exists():
            rh_path = TOOLS_DIR.parent.parent / "live-trader-v1" / "tools" / "robinhood_mcp.py"

        cmd = [
            sys.executable, str(rh_path),
            "--action", "sell" if position.get("side") == "buy" else "buy",
            "--ticker", ticker, "--qty", str(qty_to_exit),
            "--config", "config.json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return {
            "executed": result.returncode == 0,
            "qty_exited": qty_to_exit,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
    except Exception as e:
        return {"executed": False, "error": str(e)[:200]}


def main():
    parser = argparse.ArgumentParser(description="Exit decision orchestrator")
    parser.add_argument("--position-id", required=True)
    parser.add_argument("--output", default="decision.json")
    parser.add_argument("--execute", action="store_true", help="Execute the exit if decided")
    parser.add_argument("--pct", type=int, default=0, help="Override exit percentage")
    args = parser.parse_args()

    pos_path = Path("position.json")
    if not pos_path.exists():
        print(json.dumps({"error": "position.json not found"}))
        sys.exit(1)
    position = json.loads(pos_path.read_text())

    config_path = Path("config.json")
    config = json.loads(config_path.read_text()) if config_path.exists() else {}

    decision = make_exit_decision(position, config)

    if args.execute:
        exit_pct = args.pct or decision.get("suggested_exit_pct", 0)
        if exit_pct > 0:
            exec_result = execute_exit(position, exit_pct, decision)
            decision["execution"] = exec_result

    Path(args.output).write_text(json.dumps(decision, indent=2, default=str))
    print(json.dumps(decision, indent=2, default=str))


if __name__ == "__main__":
    main()
