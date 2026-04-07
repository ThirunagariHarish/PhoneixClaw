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

    # -- Step 5: TA confidence fusion (T9) — soft instead of binary veto --
    raw_confidence = float(prediction.get("confidence", 0))
    ta_score = float(ta_result.get("confidence", 0.0)) if ta_result else 0.0
    ta_verdict = ta_result.get("overall_verdict") if ta_result else None

    fused = 0.6 * raw_confidence + 0.4 * ta_score
    ta_disagrees = (
        (direction == "buy" and ta_verdict == "bearish")
        or (direction == "sell" and ta_verdict == "bullish")
    )
    if ta_disagrees:
        fused -= 0.15 * ta_score
        reasoning.append(f"TA disagrees ({ta_verdict}, conf={ta_score:.2f}) — fused penalty applied")

    # Hard veto only on catastrophic disagreement
    hard_veto = ta_disagrees and ta_score > 0.85 and raw_confidence < 0.6

    # T10: regime recalibration (no-op if no calibration stored)
    try:
        from trade_intelligence import get_intelligence
        import os as _os
        _models_dir = _os.environ.get("PHOENIX_MODELS_DIR") or str(TOOLS_DIR.parent / "models")
        _intel = get_intelligence(_models_dir)
        regime = enriched.get("market_regime") or enriched.get("regime")
        calibrated_confidence = _intel.apply_regime_calibration(raw_confidence, regime)
        if abs(calibrated_confidence - raw_confidence) > 0.02:
            reasoning.append(
                f"Regime '{regime}' recalibrated confidence "
                f"{raw_confidence:.3f} → {calibrated_confidence:.3f}"
            )
    except Exception:
        calibrated_confidence = raw_confidence

    confidence = calibrated_confidence
    prediction["confidence"] = confidence  # downstream consumers read it back
    threshold = risk_params.get("confidence_threshold", 0.65)
    model_says_trade = prediction.get("prediction") == "TRADE"

    if not model_says_trade:
        reasoning.append(f"Model says SKIP (confidence={confidence:.3f} < threshold={threshold})")
        return _build_decision("REJECT", "model_skip", steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)

    if hard_veto:
        reasoning.append("HARD VETO: TA catastrophically disagrees with low-confidence signal")
        return _build_decision("REJECT", "ta_hard_veto", steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)

    reasoning.append(f"Fused confidence = {fused:.3f} (raw={raw_confidence:.3f}, ta={ta_score:.3f})")

    # -- Build execution parameters --
    exec_params = _build_execution_params(parsed, enriched, prediction, risk_params, ta_result)

    # T2: EV gate — reject if expected value doesn't clear the threshold
    if not exec_params.get("ev_gate_pass", True):
        reasoning.append(
            f"EV gate FAILED: EV={exec_params.get('expected_value')} "
            f"E[win]={exec_params.get('expected_pnl_on_win')} "
            f"E[loss]={exec_params.get('expected_pnl_on_loss')}"
        )
        return _build_decision("REJECT", "ev_gate_failed", steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)

    # T5: stale-signal guard — if fill probability is low, only keep marketable orders
    if exec_params.get("fill_prob_60s", 1.0) < 0.4:
        reasoning.append(
            f"Low fill probability ({exec_params['fill_prob_60s']:.2f}) — marking as stale"
        )
        return _build_decision("REJECT", "stale_signal", steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)

    # -- Step 7: Paper trading mode (route to watchlist instead of broker) --
    current_mode = config.get("current_mode") or config.get("mode") or "live"
    if current_mode == "paper":
        reasoning.append(f"PAPER MODE: {direction.upper()} {ticker} @ ${exec_params.get('entry_price')} "
                         f"— adding to Robinhood watchlist (confidence={confidence:.3f})")
        try:
            from paper_portfolio import add_paper_position
            paper_result = add_paper_position(
                ticker=ticker,
                side=direction,
                price=exec_params.get("entry_price") or 0,
                quantity=1,
                signal_data={
                    "parsed": parsed,
                    "confidence": confidence,
                    "pattern_matches": prediction.get("pattern_matches", 0),
                    "reasoning": list(reasoning),
                    "exec_params": exec_params,
                },
            )
            steps.append({"step": "paper_position", "status": "ok", "result": paper_result})
        except Exception as exc:
            steps.append({"step": "paper_position", "status": "error", "error": str(exc)[:200]})

        decision = _build_decision("PAPER", None, steps, reasoning, parsed,
                                   enriched, prediction, risk_result, ta_result)
        decision["execution"] = exec_params
        decision["mode"] = "paper"
        return decision

    reasoning.append(f"APPROVED: {direction.upper()} {ticker} — "
                     f"confidence={confidence:.3f}, TA={ta_result.get('overall_verdict', 'N/A') if ta_result else 'N/A'}")

    decision = _build_decision("EXECUTE", None, steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)
    decision["execution"] = exec_params
    return decision


def _build_execution_params(parsed: dict, enriched: dict, prediction: dict,
                            risk_params: dict, ta_result: dict | None) -> dict:
    """Compute sizing, SL/TP, limit price, and exit-bucket hints.

    Phase T intelligence layer:
      T3 — learned SL/TP ATR multiples
      T5 — learned limit price adjustment (entry slippage + fillability)
      T7 — fractional Kelly sizing
      T4 — exit bucket hint for the position monitor
    All heads fall back to prior defaults when their model artifact is missing.
    """
    ticker = parsed.get("ticker", "")
    direction = parsed.get("direction", "buy")
    price = parsed.get("signal_price") or enriched.get("last_close", 0)

    atr = enriched.get("atr_14") or (price * 0.02)
    confidence = float(prediction.get("confidence", 0.65))

    max_pct = risk_params.get("max_position_size_pct", 5.0)

    # Load intelligence heads — the models dir is passed via env/config
    try:
        from trade_intelligence import get_intelligence
        import os as _os
        models_dir = _os.environ.get("PHOENIX_MODELS_DIR") or str(TOOLS_DIR.parent / "models")
        intel = get_intelligence(models_dir)
        feature_names = None
        fn_path = Path(models_dir) / "feature_names.json"
        if fn_path.exists():
            try:
                feature_names = json.loads(fn_path.read_text())
            except Exception:
                feature_names = None

        sl_mult, tp_mult = intel.predict_sl_tp_multiples(enriched, feature_names)
        e_win, e_loss = intel.predict_pnl(enriched, feature_names)
        slip_bps = intel.predict_entry_slippage_bps(enriched, feature_names)
        p_fill = intel.predict_fill_probability(enriched, feature_names)
        exit_bucket, exit_hold = intel.predict_exit_bucket(enriched, feature_names)

        # T7: fractional Kelly (uses model confidence as p_win)
        kelly_pct = intel.position_pct_kelly(confidence, e_win, e_loss, max_pct)
        position_pct = kelly_pct if kelly_pct > 0 else max_pct * min(confidence, 1.0)

        # T2: EV sanity
        ev = confidence * e_win + (1 - confidence) * e_loss
        ev_ok = ev >= intel.ev_threshold()
    except Exception as _exc:
        log.debug("[intelligence] unavailable, using priors: %s", _exc)
        sl_mult, tp_mult = 2.0, 3.0
        slip_bps, p_fill = 0.0, 0.85
        exit_bucket, exit_hold = "5_30m", 20.0
        e_win, e_loss, ev, ev_ok = 0.04, -0.03, 0.0, True
        position_pct = max_pct * min(confidence, 1.0)

    side_sign = 1 if direction == "buy" else -1
    # T5: apply slippage-based buffer to the limit price
    adjusted_price = price * (1 + (slip_bps / 10000.0) * side_sign) if price else price

    if direction == "buy":
        stop_loss = round(adjusted_price - sl_mult * atr, 2)
        take_profit = round(adjusted_price + tp_mult * atr, 2)
    else:
        stop_loss = round(adjusted_price + sl_mult * atr, 2)
        take_profit = round(adjusted_price - tp_mult * atr, 2)

    return {
        "ticker": ticker,
        "direction": direction,
        "entry_price": round(adjusted_price, 2) if adjusted_price else None,
        "signal_price": round(price, 2) if price else None,
        "stop_loss": stop_loss if adjusted_price else None,
        "take_profit": take_profit if adjusted_price else None,
        "position_size_pct": round(position_pct, 2),
        "atr_used": round(atr, 4) if atr else None,
        "sl_atr_mult": round(sl_mult, 2),
        "tp_atr_mult": round(tp_mult, 2),
        "entry_slip_bps": round(slip_bps, 2),
        "fill_prob_60s": round(p_fill, 3),
        "exit_bucket": exit_bucket,
        "expected_hold_min": round(exit_hold, 1),
        "expected_pnl_on_win": round(e_win, 4),
        "expected_pnl_on_loss": round(e_loss, 4),
        "expected_value": round(ev, 4),
        "ev_gate_pass": bool(ev_ok),
        "kelly_fraction_applied": True,
        "option_type": parsed.get("option_type"),
        "strike": parsed.get("strike"),
        "expiry": parsed.get("expiry"),
    }


def _log_signal_to_phoenix(decision: str, reason: str | None,
                            parsed: dict | None, enriched: dict | None,
                            prediction: dict | None) -> None:
    """Log this decision to the trade_signals table via Phoenix API.

    Non-blocking: fails silently if API is unreachable.
    """
    try:
        from log_trade_signal import log_signal
    except ImportError:
        return

    if not parsed:
        return

    ticker = parsed.get("ticker")
    if not ticker:
        return

    direction = parsed.get("direction")

    # Map internal decision codes → canonical values
    decision_lower = (decision or "").lower()
    if decision_lower == "execute":
        canonical = "executed"
    elif decision_lower == "reject":
        canonical = "rejected"
    elif decision_lower == "watchlist":
        canonical = "watchlist"
    elif decision_lower == "paper":
        canonical = "paper"
    else:
        canonical = "rejected"

    # Merge enriched features with the parsed signal context for the snapshot
    features = {}
    if enriched:
        features.update(enriched)
    if parsed.get("signal_price") is not None:
        features["signal_price"] = parsed.get("signal_price")

    try:
        log_signal(
            ticker=ticker,
            direction=direction,
            decision=canonical,
            predicted_prob=(prediction or {}).get("confidence"),
            model_confidence=(prediction or {}).get("confidence"),
            rejection_reason=reason,
            features=features,
        )
    except Exception:
        pass


def _build_decision(decision: str, reason: str | None, steps: list, reasoning: list,
                    parsed: dict | None = None, enriched: dict | None = None,
                    prediction: dict | None = None, risk_result: dict | None = None,
                    ta_result: dict | None = None) -> dict:
    # Log to Phoenix trade_signals table (non-blocking, silent on failure)
    _log_signal_to_phoenix(decision, reason, parsed, enriched, prediction)

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
