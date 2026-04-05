"""Decision engine: orchestrate the full signal-to-trade pipeline.

Reads a pending signal, enriches it, runs inference, checks risk + TA
confirmation, and emits a trade/reject decision with reasoning.

Usage:
    python decision_engine.py --signal pending_signals.json --config config.json --output decision.json
"""

import argparse
import json
import logging
import subprocess
import sys
import tempfile
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [decision] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Subprocess runner
# ---------------------------------------------------------------------------

def _run_tool(script: str, args: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Run a sibling tool script and capture output."""
    cmd = [sys.executable, str(TOOLS_DIR / script)] + args
    log.info("Running: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        log.error("Tool %s timed out after %ds", script, timeout)
        return -1, "", f"Timeout after {timeout}s"
    except FileNotFoundError:
        log.error("Tool script not found: %s", script)
        return -1, "", f"Script not found: {script}"


def _load_json(path: str) -> dict | list | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Signal parsing
# ---------------------------------------------------------------------------

def _parse_signal(raw_signal: dict) -> dict:
    """Normalize a raw signal from the Discord listener into a structured format."""
    content = raw_signal.get("content", "")
    parsed = {
        "raw_content": content,
        "author": raw_signal.get("author", "unknown"),
        "timestamp": raw_signal.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "message_id": raw_signal.get("message_id"),
    }

    import re

    ticker_match = re.search(r"\$([A-Z]{1,5})", content, re.IGNORECASE)
    if ticker_match:
        parsed["ticker"] = ticker_match.group(1).upper()

    price_match = re.search(r"@?\s*\$?([\d]+\.?\d*)", content)
    if price_match:
        parsed["signal_price"] = float(price_match.group(1))

    direction_patterns = {
        "buy": r"\b(buy|bought|long|calls?|entered|entry)\b",
        "sell": r"\b(sell|sold|short|puts?|exit|close|trim)\b",
    }
    for direction, pattern in direction_patterns.items():
        if re.search(pattern, content, re.IGNORECASE):
            parsed["direction"] = direction
            break

    option_match = re.search(r"(\d+\.?\d*)\s*([cp])\b", content, re.IGNORECASE)
    if option_match:
        parsed["strike"] = float(option_match.group(1))
        parsed["option_type"] = "call" if option_match.group(2).lower() == "c" else "put"

    expiry_match = re.search(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", content)
    if expiry_match:
        month = int(expiry_match.group(1))
        day = int(expiry_match.group(2))
        year = int(expiry_match.group(3)) if expiry_match.group(3) else datetime.now().year
        if year < 100:
            year += 2000
        try:
            parsed["expiry"] = f"{year}-{month:02d}-{day:02d}"
        except ValueError:
            pass

    return parsed


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------

def make_decision(signal_path: str, config_path: str, output_path: str) -> dict:
    """Full pipeline: parse → enrich → infer → risk → TA → decide."""
    steps = []
    reasoning = []

    # -- Load config --
    config = _load_json(config_path)
    if config is None:
        return {"decision": "REJECT", "reason": "Config file not found", "steps": steps}
    risk_params = config.get("risk_params", {})

    # -- Load and parse signal --
    raw_signals = _load_json(signal_path)
    if raw_signals is None:
        return {"decision": "REJECT", "reason": "Signal file not found", "steps": steps}

    if isinstance(raw_signals, list):
        if not raw_signals:
            return {"decision": "REJECT", "reason": "No signals in file", "steps": steps}
        raw_signal = raw_signals[0]
    else:
        raw_signal = raw_signals

    parsed = _parse_signal(raw_signal)
    steps.append({"step": "parse_signal", "status": "ok", "result": parsed})
    log.info("Parsed signal: ticker=%s direction=%s", parsed.get("ticker"), parsed.get("direction"))

    ticker = parsed.get("ticker")
    direction = parsed.get("direction")

    if not ticker:
        reasoning.append("No ticker found in signal")
        return _build_decision("REJECT", "no_ticker", steps, reasoning, parsed)

    if not direction:
        reasoning.append("No trade direction found in signal")
        return _build_decision("REJECT", "no_direction", steps, reasoning, parsed)

    # -- Step 1: Enrich --
    enriched_path = tempfile.mktemp(suffix=".json", prefix="enriched_")
    signal_tmp = tempfile.mktemp(suffix=".json", prefix="signal_")
    Path(signal_tmp).write_text(json.dumps(parsed, indent=2))

    rc, stdout, stderr = _run_tool("enrich_single.py",
                                   ["--signal", signal_tmp, "--output", enriched_path])
    enrich_step = {"step": "enrich", "return_code": rc}
    if rc != 0:
        enrich_step["error"] = stderr[-500:] if stderr else "unknown error"
        steps.append(enrich_step)
        reasoning.append("Enrichment failed, proceeding with limited data")
        enriched = parsed
    else:
        enriched = _load_json(enriched_path) or parsed
        enrich_step["status"] = "ok"
        enrich_step["features_count"] = len([k for k in enriched if k not in parsed])
        steps.append(enrich_step)
        reasoning.append(f"Enriched with {enrich_step['features_count']} market features")

    # -- Step 2: Inference --
    prediction_path = tempfile.mktemp(suffix=".json", prefix="prediction_")
    rc, stdout, stderr = _run_tool("inference.py",
                                   ["--features", enriched_path if Path(enriched_path).exists() else signal_tmp,
                                    "--output", prediction_path])
    inference_step = {"step": "inference", "return_code": rc}
    if rc != 0:
        inference_step["error"] = stderr[-500:] if stderr else "unknown error"
        inference_step["status"] = "skipped"
        steps.append(inference_step)
        prediction = {"prediction": "SKIP", "confidence": 0.0, "pattern_matches": 0}
        reasoning.append("Inference failed — model may not be loaded")
    else:
        prediction = _load_json(prediction_path) or {"prediction": "SKIP", "confidence": 0.0}
        inference_step["status"] = "ok"
        inference_step["prediction"] = prediction.get("prediction")
        inference_step["confidence"] = prediction.get("confidence")
        steps.append(inference_step)
        reasoning.append(f"Model prediction: {prediction.get('prediction')} "
                         f"(confidence={prediction.get('confidence', 0):.3f}, "
                         f"patterns={prediction.get('pattern_matches', 0)})")

    # -- Step 3: Risk check --
    portfolio_path = Path("portfolio.json")
    portfolio = json.loads(portfolio_path.read_text()) if portfolio_path.exists() else {
        "open_positions": 0, "daily_pnl_pct": 0
    }
    if isinstance(portfolio.get("positions"), list):
        open_count = len([p for p in portfolio["positions"] if p.get("status") == "open"])
        portfolio["open_positions"] = open_count
    if "daily_pnl" in portfolio and isinstance(portfolio["daily_pnl"], list):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = [d for d in portfolio["daily_pnl"] if d.get("date") == today]
        portfolio["daily_pnl_pct"] = sum(d.get("pnl", 0) for d in daily)

    risk_tmp = tempfile.mktemp(suffix=".json", prefix="risk_signal_")
    pred_tmp = tempfile.mktemp(suffix=".json", prefix="risk_pred_")
    port_tmp = tempfile.mktemp(suffix=".json", prefix="risk_port_")
    risk_out = tempfile.mktemp(suffix=".json", prefix="risk_result_")
    Path(risk_tmp).write_text(json.dumps(enriched, default=str))
    Path(pred_tmp).write_text(json.dumps(prediction, default=str))
    Path(port_tmp).write_text(json.dumps(portfolio, default=str))

    rc, stdout, stderr = _run_tool("risk_check.py",
                                   ["--signal", risk_tmp, "--prediction", pred_tmp,
                                    "--portfolio", port_tmp, "--config", config_path,
                                    "--output", risk_out])
    risk_step = {"step": "risk_check", "return_code": rc}
    if rc != 0:
        risk_step["error"] = stderr[-500:] if stderr else "unknown error"
        risk_step["status"] = "failed"
        steps.append(risk_step)
        reasoning.append("Risk check failed")
        return _build_decision("REJECT", "risk_check_failed", steps, reasoning, parsed, enriched, prediction)

    risk_result = _load_json(risk_out) or {"approved": False, "rejection_reason": "unknown"}
    risk_step["status"] = "ok"
    risk_step["approved"] = risk_result.get("approved")
    risk_step["checks"] = risk_result.get("checks")
    steps.append(risk_step)

    if not risk_result.get("approved"):
        reasoning.append(f"Risk rejected: {risk_result.get('rejection_reason')}")
        return _build_decision("REJECT", risk_result.get("rejection_reason", "risk_failed"),
                               steps, reasoning, parsed, enriched, prediction, risk_result)
    reasoning.append("Risk check passed")

    # -- Step 4: TA confirmation --
    ta_path = tempfile.mktemp(suffix=".json", prefix="ta_")
    rc, stdout, stderr = _run_tool("technical_analysis.py",
                                   ["--ticker", ticker, "--output", ta_path])
    ta_step = {"step": "ta_confirmation", "return_code": rc}
    ta_result = None
    if rc != 0:
        ta_step["status"] = "skipped"
        ta_step["error"] = stderr[-500:] if stderr else "unknown error"
        reasoning.append("TA check skipped (tool unavailable)")
    else:
        ta_result = _load_json(ta_path)
        ta_step["status"] = "ok"
        if ta_result:
            ta_step["verdict"] = ta_result.get("overall_verdict")
            ta_step["confidence"] = ta_result.get("confidence")
            ta_step["patterns"] = len(ta_result.get("all_patterns", []))
            reasoning.append(f"TA verdict: {ta_result.get('overall_verdict')} "
                             f"(confidence={ta_result.get('confidence', 0):.3f})")
    steps.append(ta_step)

    # -- Step 5: TA alignment check --
    ta_aligned = True
    if ta_result and ta_result.get("overall_verdict"):
        ta_verdict = ta_result["overall_verdict"]
        if direction == "buy" and ta_verdict == "bearish" and ta_result.get("confidence", 0) > 0.5:
            ta_aligned = False
            reasoning.append("TA strongly contradicts buy signal (bearish with high confidence)")
        elif direction == "sell" and ta_verdict == "bullish" and ta_result.get("confidence", 0) > 0.5:
            ta_aligned = False
            reasoning.append("TA strongly contradicts sell signal (bullish with high confidence)")
        else:
            reasoning.append("TA does not contradict signal direction")

    # -- Step 6: Final decision --
    confidence = prediction.get("confidence", 0)
    threshold = risk_params.get("confidence_threshold", 0.65)
    model_says_trade = prediction.get("prediction") == "TRADE"

    if not model_says_trade:
        reasoning.append(f"Model says SKIP (confidence={confidence:.3f} < threshold={threshold})")
        return _build_decision("REJECT", "model_skip", steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)

    if not ta_aligned:
        reasoning.append("Rejected due to TA misalignment despite model approval")
        return _build_decision("REJECT", "ta_misalignment", steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)

    # -- Build execution parameters --
    exec_params = _build_execution_params(parsed, enriched, prediction, risk_params, ta_result)
    reasoning.append(f"APPROVED: {direction.upper()} {ticker} — "
                     f"confidence={confidence:.3f}, TA={ta_result.get('overall_verdict', 'N/A') if ta_result else 'N/A'}")

    decision = _build_decision("EXECUTE", None, steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)
    decision["execution"] = exec_params
    return decision


def _build_execution_params(parsed: dict, enriched: dict, prediction: dict,
                            risk_params: dict, ta_result: dict | None) -> dict:
    """Compute position sizing and stop-loss/take-profit levels."""
    ticker = parsed.get("ticker", "")
    direction = parsed.get("direction", "buy")
    price = parsed.get("signal_price") or enriched.get("last_close", 0)

    atr = enriched.get("atr_14") or (price * 0.02)
    confidence = prediction.get("confidence", 0.65)

    max_pct = risk_params.get("max_position_size_pct", 5.0)
    position_pct = max_pct * min(confidence, 1.0)

    if direction == "buy":
        stop_loss = round(price - 2 * atr, 2)
        take_profit = round(price + 3 * atr, 2)
    else:
        stop_loss = round(price + 2 * atr, 2)
        take_profit = round(price - 3 * atr, 2)

    return {
        "ticker": ticker,
        "direction": direction,
        "entry_price": round(price, 2) if price else None,
        "stop_loss": stop_loss if price else None,
        "take_profit": take_profit if price else None,
        "position_size_pct": round(position_pct, 2),
        "atr_used": round(atr, 4) if atr else None,
        "option_type": parsed.get("option_type"),
        "strike": parsed.get("strike"),
        "expiry": parsed.get("expiry"),
    }


def _build_decision(decision: str, reason: str | None, steps: list, reasoning: list,
                    parsed: dict | None = None, enriched: dict | None = None,
                    prediction: dict | None = None, risk_result: dict | None = None,
                    ta_result: dict | None = None) -> dict:
    result = {
        "decision": decision,
        "reason": reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reasoning": reasoning,
        "steps": steps,
    }
    if parsed:
        result["parsed_signal"] = {
            "ticker": parsed.get("ticker"),
            "direction": parsed.get("direction"),
            "signal_price": parsed.get("signal_price"),
            "option_type": parsed.get("option_type"),
            "strike": parsed.get("strike"),
            "expiry": parsed.get("expiry"),
        }
    if prediction:
        result["model_prediction"] = {
            "prediction": prediction.get("prediction"),
            "confidence": prediction.get("confidence"),
            "pattern_matches": prediction.get("pattern_matches"),
        }
    if risk_result:
        result["risk_check"] = risk_result
    if ta_result:
        result["ta_summary"] = {
            "verdict": ta_result.get("overall_verdict"),
            "confidence": ta_result.get("confidence"),
            "bullish_signals": ta_result.get("bullish_signals_total"),
            "bearish_signals": ta_result.get("bearish_signals_total"),
            "patterns_detected": len(ta_result.get("all_patterns", [])),
        }
    return result


def _json_safe(obj):
    """Recursively convert numpy/pandas types for JSON."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    try:
        import numpy as _np
        if isinstance(obj, (_np.floating, _np.float64, _np.float32)):
            return None if _np.isnan(obj) else round(float(obj), 6)
        if isinstance(obj, (_np.integer, _np.int64)):
            return int(obj)
        if isinstance(obj, _np.bool_):
            return bool(obj)
    except ImportError:
        pass
    return obj


def main():
    parser = argparse.ArgumentParser(
        description="Decision engine: full signal-to-trade pipeline")
    parser.add_argument("--signal", required=True, help="Path to pending_signals.json")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    parser.add_argument("--output", default="decision.json", help="Output decision JSON")
    args = parser.parse_args()

    if not Path(args.signal).exists():
        log.error("Signal file not found: %s", args.signal)
        sys.exit(1)

    if not Path(args.config).exists():
        log.error("Config file not found: %s", args.config)
        sys.exit(1)

    log.info("Starting decision pipeline")
    log.info("  Signal: %s", args.signal)
    log.info("  Config: %s", args.config)

    decision = make_decision(args.signal, args.config, args.output)
    decision = _json_safe(decision)

    with open(args.output, "w") as f:
        json.dump(decision, f, indent=2, default=str)

    summary = {
        "decision": decision["decision"],
        "reason": decision.get("reason"),
        "ticker": decision.get("parsed_signal", {}).get("ticker"),
        "direction": decision.get("parsed_signal", {}).get("direction"),
        "confidence": decision.get("model_prediction", {}).get("confidence"),
        "output": args.output,
    }
    print(json.dumps(summary))

    if decision["decision"] == "EXECUTE":
        log.info("DECISION: EXECUTE trade")
    else:
        log.info("DECISION: REJECT — %s", decision.get("reason"))


if __name__ == "__main__":
    main()
