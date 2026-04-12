"""Decision engine — focused tool for building execution parameters and applying trade gates.

This module provides:
  - ``_build_execution_params`` — sizing, SL/TP, limit price, exit-bucket hints
  - ``make_decision`` — full signal-to-trade pipeline (parse → enrich → infer → risk → TA → decide)

The Claude agent can either call ``make_decision`` as a single CLI command or drive
each step individually (parse_signal → enrich_single → inference → risk_check → TA)
and call ``_build_execution_params`` directly.

Usage:
    python decision_engine.py --signal pending_signals.json --config config.json --output decision.json
"""
from __future__ import annotations

import argparse
import json
import logging
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


def _load_json(path: str) -> dict | list | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load %s: %s", path, exc)
        return None


def _build_execution_params(parsed: dict, enriched: dict, prediction: dict,
                            risk_params: dict, ta_result: dict | None) -> dict:
    """Compute sizing, SL/TP, limit price, and exit-bucket hints.

    Uses trade_intelligence heads when available (learned SL/TP ATR multiples,
    entry slippage, fill probability, fractional Kelly sizing, exit bucket hints).
    Falls back to safe priors when model artifacts are missing.
    """
    ticker = parsed.get("ticker", "")
    direction = parsed.get("direction", "buy")
    price = parsed.get("signal_price") or enriched.get("last_close", 0)

    atr = enriched.get("atr_14") or (price * 0.02)
    confidence = float(prediction.get("confidence", 0.65))
    max_pct = risk_params.get("max_position_size_pct", 5.0)

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
        kelly_pct = intel.position_pct_kelly(confidence, e_win, e_loss, max_pct)
        position_pct = kelly_pct if kelly_pct > 0 else max_pct * min(confidence, 1.0)
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


def make_decision(signal_path: str, config_path: str, output_path: str) -> dict:
    """Full pipeline: parse -> enrich -> infer -> risk -> TA -> decide.

    Each step uses direct imports (not subprocesses). The Claude agent can also
    drive these steps individually for more control.
    """
    from parse_signal import parse as parse_signal

    steps: list[dict] = []
    reasoning: list[str] = []

    config = _load_json(config_path)
    if config is None:
        return {"decision": "REJECT", "reason": "Config file not found", "steps": steps}
    risk_params = config.get("risk_params", {})

    raw_signals = _load_json(signal_path)
    if raw_signals is None:
        return {"decision": "REJECT", "reason": "Signal file not found", "steps": steps}

    if isinstance(raw_signals, list):
        if not raw_signals:
            return {"decision": "REJECT", "reason": "No signals in file", "steps": steps}
        raw_signal = raw_signals[0]
    else:
        raw_signal = raw_signals

    parsed = parse_signal(raw_signal)
    steps.append({"step": "parse_signal", "status": "ok"})

    ticker = parsed.get("ticker")
    direction = parsed.get("direction")
    if not ticker:
        reasoning.append("No ticker found in signal")
        return _build_decision("REJECT", "no_ticker", steps, reasoning, parsed)
    if not direction:
        reasoning.append("No trade direction found in signal")
        return _build_decision("REJECT", "no_direction", steps, reasoning, parsed)

    try:
        from market_session_gate import outside_rth_watchlist_payload

        gate = outside_rth_watchlist_payload(parsed, config, steps, reasoning)
        if gate:
            decision = _build_decision(
                "WATCHLIST",
                gate["reason"],
                steps,
                reasoning,
                parsed,
                gate["enriched"],
                gate["prediction"],
                None,
            )
            decision["market_status"] = gate["market_status"]
            decision["execution"] = {"deferred": True, "reason": "outside_regular_session"}
            return decision
    except Exception as exc:
        log.debug("market_session_gate skipped: %s", exc)

    # Enrich
    enriched = parsed.copy()
    try:
        from enrich_single import enrich_signal
        enriched = enrich_signal(parsed)
        feature_count = len([k for k in enriched if k not in parsed])
        steps.append({"step": "enrich", "status": "ok", "features_count": feature_count})
        reasoning.append(f"Enriched with {feature_count} market features")
    except Exception as e:
        steps.append({"step": "enrich", "status": "failed", "error": str(e)[:200]})
        reasoning.append(f"Enrichment failed: {e}")

    # Inference
    prediction = {"prediction": "SKIP", "confidence": 0.0, "pattern_matches": 0}
    try:
        from inference import predict
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, prefix="feat_") as f:
            json.dump(_json_safe(enriched), f, default=str)
            features_path = f.name
        try:
            prediction = predict(features_path, str(Path(config.get("models_dir", "models"))))
        finally:
            Path(features_path).unlink(missing_ok=True)
        steps.append({"step": "inference", "status": "ok",
                       "prediction": prediction.get("prediction"),
                       "confidence": prediction.get("confidence")})
        reasoning.append(f"Model: {prediction.get('prediction')} "
                         f"(confidence={prediction.get('confidence', 0):.3f})")
    except Exception as e:
        steps.append({"step": "inference", "status": "failed", "error": str(e)[:200]})
        reasoning.append(f"Inference failed: {e}")

    # No-models gate: if no trained models exist, route to watchlist for observation
    models_dir = Path(config.get("models_dir", "models"))
    has_models = models_dir.exists() and any(models_dir.glob("*_model.pkl"))

    if not has_models:
        reasoning.append("No trained models available — adding to watchlist for observation")
        try:
            from robinhood_mcp_client import add_to_watchlist
            add_to_watchlist(ticker, config=config)
            steps.append({"step": "watchlist_add", "status": "ok", "ticker": ticker})
        except Exception as exc:
            steps.append({"step": "watchlist_add", "status": "skipped", "error": str(exc)[:120]})
        decision = _build_decision(
            "WATCHLIST", "no_backtesting_data", steps, reasoning, parsed,
            enriched, prediction,
        )
        return decision

    # Risk check
    portfolio = {"open_positions": 0, "daily_pnl_pct": 0}
    portfolio_path = Path("portfolio.json")
    if portfolio_path.exists():
        try:
            portfolio = json.loads(portfolio_path.read_text())
        except Exception:
            pass
    try:
        from risk_check import check_risk
        risk_result = check_risk(enriched, prediction, portfolio, config)
        steps.append({"step": "risk_check", "status": "ok", "approved": risk_result.get("approved")})
        if not risk_result.get("approved"):
            reasoning.append(f"Risk rejected: {risk_result.get('rejection_reason')}")
            return _build_decision("REJECT", risk_result.get("rejection_reason", "risk_failed"),
                                   steps, reasoning, parsed, enriched, prediction, risk_result)
        reasoning.append("Risk check passed")
    except Exception as e:
        steps.append({"step": "risk_check", "status": "failed", "error": str(e)[:200]})
        return _build_decision("REJECT", "risk_check_error", steps, reasoning, parsed, enriched, prediction)

    # TA confirmation
    ta_result = None
    try:
        from technical_analysis import analyze_ticker
        ta_result = analyze_ticker(ticker)
        steps.append({"step": "ta_confirmation", "status": "ok",
                       "verdict": ta_result.get("overall_verdict")})
        reasoning.append(f"TA: {ta_result.get('overall_verdict')} "
                         f"(conf={ta_result.get('confidence', 0):.2f})")
    except Exception as e:
        steps.append({"step": "ta_confirmation", "status": "skipped", "error": str(e)[:200]})
        reasoning.append("TA check skipped")

    # TA confidence fusion
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
        reasoning.append(f"TA disagrees ({ta_verdict}) — fused penalty applied")

    hard_veto = ta_disagrees and ta_score > 0.85 and raw_confidence < 0.6

    # Regime recalibration
    try:
        from trade_intelligence import get_intelligence
        import os as _os
        _models_dir = _os.environ.get("PHOENIX_MODELS_DIR") or str(TOOLS_DIR.parent / "models")
        _intel = get_intelligence(_models_dir)
        regime = enriched.get("market_regime") or enriched.get("regime")
        calibrated_confidence = _intel.apply_regime_calibration(raw_confidence, regime)
    except Exception:
        calibrated_confidence = raw_confidence

    confidence = calibrated_confidence
    prediction["confidence"] = confidence
    model_says_trade = prediction.get("prediction") == "TRADE"

    if not model_says_trade:
        reasoning.append(f"Model says SKIP (confidence={confidence:.3f})")
        return _build_decision("REJECT", "model_skip", steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)
    if hard_veto:
        reasoning.append("HARD VETO: TA catastrophically disagrees")
        return _build_decision("REJECT", "ta_hard_veto", steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)

    exec_params = _build_execution_params(parsed, enriched, prediction, risk_params, ta_result)

    if not exec_params.get("ev_gate_pass", True):
        reasoning.append(f"EV gate FAILED: EV={exec_params.get('expected_value')}")
        return _build_decision("REJECT", "ev_gate_failed", steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)

    if exec_params.get("fill_prob_60s", 1.0) < 0.4:
        reasoning.append(f"Low fill probability ({exec_params['fill_prob_60s']:.2f})")
        return _build_decision("REJECT", "stale_signal", steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)

    # Paper mode
    current_mode = config.get("current_mode") or config.get("mode") or "live"
    if current_mode == "paper":
        reasoning.append(f"PAPER MODE: {direction.upper()} {ticker}")
        try:
            from paper_portfolio import add_paper_position
            add_paper_position(ticker=ticker, side=direction,
                               price=exec_params.get("entry_price") or 0,
                               quantity=1, signal_data={"parsed": parsed, "confidence": confidence})
        except Exception:
            pass
        decision = _build_decision("PAPER", None, steps, reasoning, parsed,
                                   enriched, prediction, risk_result, ta_result)
        decision["execution"] = exec_params
        return decision

    reasoning.append(f"APPROVED: {direction.upper()} {ticker} (confidence={confidence:.3f})")
    decision = _build_decision("EXECUTE", None, steps, reasoning, parsed,
                               enriched, prediction, risk_result, ta_result)
    decision["execution"] = exec_params
    return decision


def _log_signal_to_phoenix(decision: str, reason: str | None,
                           parsed: dict | None, enriched: dict | None,
                           prediction: dict | None) -> None:
    try:
        from log_trade_signal import log_signal
    except ImportError:
        return
    if not parsed or not parsed.get("ticker"):
        return
    decision_lower = (decision or "").lower()
    canonical = {
        "execute": "executed",
        "reject": "rejected",
        "watchlist": "watchlist",
        "paper": "paper",
    }.get(decision_lower, "rejected")
    features = dict(enriched or {})
    if parsed.get("signal_price") is not None:
        features["signal_price"] = parsed["signal_price"]
    try:
        log_signal(ticker=parsed["ticker"], direction=parsed.get("direction"),
                   decision=canonical, predicted_prob=(prediction or {}).get("confidence"),
                   model_confidence=(prediction or {}).get("confidence"),
                   rejection_reason=reason, features=features,
                   source_message_id=parsed.get("message_id"))
    except Exception:
        pass


def _build_decision(decision: str, reason: str | None, steps: list, reasoning: list,
                    parsed: dict | None = None, enriched: dict | None = None,
                    prediction: dict | None = None, risk_result: dict | None = None,
                    ta_result: dict | None = None) -> dict:
    _log_signal_to_phoenix(decision, reason, parsed, enriched, prediction)

    result: dict = {
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
        }
    return result


def _json_safe(obj: object) -> object:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Decision engine")
    parser.add_argument("--signal", required=True)
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--output", default="decision.json")
    args = parser.parse_args()

    if not Path(args.signal).exists():
        log.error("Signal file not found: %s", args.signal)
        sys.exit(1)

    decision = make_decision(args.signal, args.config, args.output)
    decision = _json_safe(decision)

    Path(args.output).write_text(json.dumps(decision, indent=2, default=str))
    print(json.dumps({
        "decision": decision["decision"],
        "reason": decision.get("reason"),
        "ticker": decision.get("parsed_signal", {}).get("ticker"),
    }))


if __name__ == "__main__":
    main()
