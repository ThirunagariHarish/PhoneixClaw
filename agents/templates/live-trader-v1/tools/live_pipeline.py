"""Live trading pipeline — async loop consuming signals from Redis stream.

Replaces the subprocess-based decision_engine.py with in-process calls:
  discord_redis_consumer → Redis stream → enrich → predict → risk_check → decide → report

Usage:
    python live_pipeline.py --config config.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [pipeline] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).resolve().parent


def _json_safe(obj):
    """Convert numpy/pandas types for JSON serialization."""
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


async def process_signal(raw_signal: dict, config: dict) -> dict:
    """Process a single signal through the full pipeline in-process.

    Returns a decision dict with: decision, reasoning, steps, execution params.
    """
    steps = []
    reasoning = []
    risk_params = config.get("risk_params", {})

    # -- Step 1: Parse signal (reuse decision_engine logic) --
    from decision_engine import _build_execution_params, _parse_signal
    parsed = _parse_signal(raw_signal)
    steps.append({"step": "parse_signal", "status": "ok"})
    log.info("Parsed: ticker=%s direction=%s priority=%s",
             parsed.get("ticker"), parsed.get("direction"), raw_signal.get("priority"))

    ticker = parsed.get("ticker")
    direction = parsed.get("direction")

    if not ticker:
        reasoning.append("No ticker found in signal")
        return _build_result("REJECT", "no_ticker", steps, reasoning, parsed)

    if not direction:
        reasoning.append("No trade direction found in signal")
        return _build_result("REJECT", "no_direction", steps, reasoning, parsed)

    # -- Step 2: Enrich (in-process, no subprocess) --
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
        log.warning("Enrichment failed: %s", e)

    # -- Step 3: Inference (needs a temp file for model loading) --
    prediction = {"prediction": "SKIP", "confidence": 0.0, "pattern_matches": 0}
    try:
        from inference import predict

        # Write enriched features to temp file (inference.predict reads from file)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, prefix="feat_") as f:
            json.dump(_json_safe(enriched), f, default=str)
            features_path = f.name

        models_dir = str(Path(config.get("models_dir", "models")))
        try:
            prediction = predict(features_path, models_dir)
        finally:
            Path(features_path).unlink(missing_ok=True)
        steps.append({
            "step": "inference", "status": "ok",
            "prediction": prediction.get("prediction"),
            "confidence": prediction.get("confidence"),
        })
        reasoning.append(
            f"Model: {prediction.get('prediction')} "
            f"(confidence={prediction.get('confidence', 0):.3f}, "
            f"patterns={prediction.get('pattern_matches', 0)})"
        )
    except Exception as e:
        steps.append({"step": "inference", "status": "failed", "error": str(e)[:200]})
        reasoning.append(f"Inference failed: {e}")
        log.warning("Inference failed: %s", e)

    # -- Step 4: Risk check (in-process) --
    portfolio_path = Path("portfolio.json")
    portfolio = {"open_positions": 0, "daily_pnl_pct": 0}
    if portfolio_path.exists():
        try:
            portfolio = json.loads(portfolio_path.read_text())
            if isinstance(portfolio.get("positions"), list):
                portfolio["open_positions"] = len([p for p in portfolio["positions"] if p.get("status") == "open"])
        except Exception:
            pass

    try:
        from risk_check import check_risk
        risk_result = check_risk(enriched, prediction, portfolio, config)
        steps.append({"step": "risk_check", "status": "ok", "approved": risk_result.get("approved")})

        if not risk_result.get("approved"):
            reasoning.append(f"Risk rejected: {risk_result.get('rejection_reason')}")
            return _build_result("REJECT", risk_result.get("rejection_reason", "risk_failed"),
                                 steps, reasoning, parsed, prediction, risk_result)
        reasoning.append("Risk check passed")
    except Exception as e:
        steps.append({"step": "risk_check", "status": "failed", "error": str(e)[:200]})
        reasoning.append(f"Risk check failed: {e}")
        return _build_result("REJECT", "risk_check_error", steps, reasoning, parsed, prediction)

    # -- Step 5: TA confirmation (optional, in-process) --
    ta_result = None
    try:
        from technical_analysis import analyze_ticker
        ta_result = analyze_ticker(ticker)
        steps.append({
            "step": "ta_confirmation", "status": "ok",
            "verdict": ta_result.get("overall_verdict"),
        })

        # Check TA alignment
        ta_verdict = ta_result.get("overall_verdict", "")
        ta_conf = ta_result.get("confidence", 0)
        if direction == "buy" and ta_verdict == "bearish" and ta_conf > 0.5:
            reasoning.append("TA strongly contradicts buy signal")
            return _build_result("REJECT", "ta_misalignment", steps, reasoning, parsed, prediction, risk_result)
        elif direction == "sell" and ta_verdict == "bullish" and ta_conf > 0.5:
            reasoning.append("TA strongly contradicts sell signal")
            return _build_result("REJECT", "ta_misalignment", steps, reasoning, parsed, prediction, risk_result)
        reasoning.append(f"TA: {ta_verdict} (conf={ta_conf:.2f})")
    except Exception as e:
        steps.append({"step": "ta_confirmation", "status": "skipped", "error": str(e)[:200]})
        reasoning.append("TA check skipped")

    # -- Step 6: Model must say TRADE --
    if prediction.get("prediction") != "TRADE":
        reasoning.append(f"Model says SKIP (confidence={prediction.get('confidence', 0):.3f})")
        return _build_result("REJECT", "model_skip", steps, reasoning, parsed, prediction, risk_result)

    # -- Step 7: EXECUTE --
    exec_params = _build_execution_params(parsed, enriched, prediction, risk_params, ta_result)
    reasoning.append(f"APPROVED: {direction.upper()} {ticker}")

    result = _build_result("EXECUTE", None, steps, reasoning, parsed, prediction, risk_result)
    result["execution"] = exec_params
    return result


def _build_result(decision: str, reason: str | None, steps: list, reasoning: list,
                  parsed: dict | None = None, prediction: dict | None = None,
                  risk_result: dict | None = None) -> dict:
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
        }
    if prediction:
        result["model_prediction"] = {
            "prediction": prediction.get("prediction"),
            "confidence": prediction.get("confidence"),
            "pattern_matches": prediction.get("pattern_matches"),
        }
    if risk_result:
        result["risk_check"] = risk_result
    return result


async def _redis_signal_stream(config: dict):
    """Async generator that yields signal dicts from the Redis stream.

    Reads from `stream:channel:{connector_id}` (preferred) or
    `stream:channel:{channel_id}` (fallback), honouring the persisted cursor.
    Yields indefinitely until the process is stopped.
    """
    import os

    try:
        import redis.asyncio as aioredis
    except ImportError:
        log.error("[pipeline] redis-py not installed — cannot consume signals")
        return

    from discord_redis_consumer import _load_cursor_data, _save_cursor

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    connector_id = config.get("connector_id")
    channel_id = config.get("channel_id", connector_id)

    if not connector_id and not channel_id:
        log.error("[pipeline] config missing both connector_id and channel_id — cannot start Redis stream")
        return

    primary_key = f"stream:channel:{connector_id}" if connector_id else None
    fallback_key = f"stream:channel:{channel_id}"

    try:
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
    except Exception as exc:
        log.error("[pipeline] Redis connect failed: %s", exc)
        return

    # Choose stream key: try connector_id key first, fall back to channel_id key.
    stream_key = primary_key or fallback_key
    if primary_key and primary_key != fallback_key:
        try:
            if await redis_client.xlen(primary_key) == 0 and await redis_client.xlen(fallback_key) > 0:
                stream_key = fallback_key
                log.info("[pipeline] Using fallback stream key '%s'", stream_key)
            else:
                log.info("[pipeline] Using primary stream key '%s'", stream_key)
        except Exception:
            pass

    last_id, total = _load_cursor_data(stream_key)
    log.info("[pipeline] Redis signal stream starting on '%s' (cursor=%s)", stream_key, last_id)

    try:
        while True:
            try:
                result = await redis_client.xread({stream_key: last_id}, count=50, block=5000)
                if not result:
                    continue
                for _stream, entries in result:
                    for msg_id, data in entries:
                        last_id = msg_id
                        total += 1
                        _save_cursor(stream_key, last_id, total)
                        yield {
                            "stream_id": msg_id,
                            "channel_id": data.get("channel_id", channel_id),
                            "channel": data.get("channel", ""),
                            "author": data.get("author", ""),
                            "content": data.get("content", ""),
                            "timestamp": data.get("timestamp", ""),
                            "message_id": data.get("message_id", ""),
                        }
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("[pipeline] Redis xread error: %s", exc, exc_info=True)
                await asyncio.sleep(2)
    finally:
        try:
            await redis_client.aclose()
        except Exception:
            pass


async def run_pipeline(config: dict):
    """Main pipeline loop — consume signals from Redis stream, process, report."""
    from report_to_phoenix import report_heartbeat, report_trade

    signals_processed = 0
    trades_today = 0

    log.info("Pipeline started, waiting for signals from Redis stream...")

    # Run heartbeat in background
    async def heartbeat_loop():
        while True:
            await asyncio.sleep(60)
            try:
                await report_heartbeat(config, {
                    "status": "listening",
                    "signals_processed": signals_processed,
                    "trades_today": trades_today,
                })
            except Exception as e:
                log.debug("Heartbeat failed: %s", e)

    asyncio.create_task(heartbeat_loop())

    async for signal in _redis_signal_stream(config):
        signals_processed += 1
        log.info("Processing signal #%d: %s", signals_processed, signal.get("content", "")[:80])

        try:
            decision = await process_signal(signal, config)
            decision = _json_safe(decision)

            # Save decision to file for debugging
            decision_file = Path("last_decision.json")
            decision_file.write_text(json.dumps(decision, indent=2, default=str))

            if decision["decision"] == "EXECUTE":
                trades_today += 1
                log.info("EXECUTE: %s %s",
                         decision.get("parsed_signal", {}).get("direction"),
                         decision.get("parsed_signal", {}).get("ticker"))

                # Report trade to Phoenix API
                try:
                    trade_data = {
                        "ticker": decision["parsed_signal"]["ticker"],
                        "side": decision["parsed_signal"]["direction"],
                        "entry_price": decision.get("execution", {}).get("entry_price", 0),
                        "quantity": 1,
                        "model_confidence": decision.get("model_prediction", {}).get("confidence"),
                        "pattern_matches": decision.get("model_prediction", {}).get("pattern_matches"),
                        "reasoning": " | ".join(decision.get("reasoning", [])),
                        "signal_raw": signal.get("content", ""),
                    }
                    await report_trade(config, trade_data)
                except Exception as e:
                    log.error("Failed to report trade: %s", e)

                # Output for execution by robinhood_mcp — suppressed in paper mode
                if config.get("paper_mode"):
                    log.warning("[pipeline] Paper mode: EXECUTE suppressed — call log_paper_trade.py instead")
                else:
                    print(json.dumps({
                        "event": "trade_decision",
                        "decision": "EXECUTE",
                        **decision.get("execution", {}),
                    }))
                    sys.stdout.flush()
            else:
                log.info("REJECT: %s — %s",
                         decision.get("parsed_signal", {}).get("ticker"),
                         decision.get("reason"))
        except Exception as e:
            log.error("Pipeline error processing signal: %s", e, exc_info=True)


def main():
    parser = argparse.ArgumentParser(description="Live trading pipeline")
    parser.add_argument("--config", default="config.json", help="Path to agent config.json")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    asyncio.run(run_pipeline(config))


if __name__ == "__main__":
    main()
