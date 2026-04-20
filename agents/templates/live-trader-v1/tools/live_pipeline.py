"""Live trading pipeline — async hot-loop consuming signals from Redis stream.

This is a **latency-optimized** path the Claude agent can start when it needs
all pipeline steps to run in-process without per-signal LLM overhead.  The agent
can alternatively drive each tool individually for more control.

Usage:
    python live_pipeline.py --config config.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class _FlushHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()


_handler = _FlushHandler(sys.stderr)
_handler.setFormatter(logging.Formatter("%(asctime)s [pipeline] %(levelname)s %(message)s"))
logging.root.handlers = [_handler]
logging.root.setLevel(logging.INFO)
log = logging.getLogger(__name__)

MAX_SIGNAL_AGE_SECONDS = int(os.getenv("MAX_SIGNAL_AGE_SECONDS", "300"))


def _bypass_ml_channels() -> set[str]:
    raw = os.getenv("BYPASS_ML_CHANNELS", "text-trades")
    return {c.strip().lower() for c in raw.split(",") if c.strip()}

# Shared mutable state for the health status file
_pipeline_state: dict = {
    "started_at": None,
    "signals_processed": 0,
    "trades_today": 0,
    "last_signal_time": None,
    "last_error": None,
    "redis_connected": False,
    "stream_key": None,
}


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


async def _startup_diagnostic(config: dict) -> dict:
    """Run pre-flight checks and report results to Phoenix and the status file."""
    diag: dict = {
        "redis_ping": False,
        "stream_length": -1,
        "stream_key": None,
        "redis_url": None,
        "imports": {},
    }

    redis_url = config.get("redis_url") or os.getenv("REDIS_URL", "redis://localhost:6379")
    connector_id = config.get("connector_id", "")
    channel_id = config.get("channel_id", connector_id)
    stream_key = f"stream:channel:{connector_id}" if connector_id else f"stream:channel:{channel_id}"
    diag["redis_url"] = redis_url
    diag["stream_key"] = stream_key

    # 1. PING Redis
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(redis_url, decode_responses=True)
        pong = await client.ping()
        diag["redis_ping"] = bool(pong)
        log.info("Redis PING: %s (%s)", pong, redis_url)
    except Exception as exc:
        log.error("Redis PING failed: %s", exc)
        diag["redis_ping_error"] = str(exc)[:200]
        client = None

    # 2. XLEN the stream
    if client and diag["redis_ping"]:
        try:
            length = await client.xlen(stream_key)
            diag["stream_length"] = length
            log.info("Stream '%s' has %d messages", stream_key, length)
        except Exception as exc:
            log.warning("XLEN failed for %s: %s", stream_key, exc)
            diag["stream_length_error"] = str(exc)[:200]
        try:
            await client.aclose()
        except Exception:
            pass

    # 3. Test key imports
    for mod_name in ("parse_signal", "decision_engine", "report_to_phoenix"):
        try:
            __import__(mod_name)
            diag["imports"][mod_name] = "ok"
        except Exception as exc:
            diag["imports"][mod_name] = str(exc)[:120]
            log.error("Import %s FAILED: %s", mod_name, exc)
    for mod_path in ("shared.utils.signal_parser",):
        try:
            __import__(mod_path)
            diag["imports"][mod_path] = "ok"
        except Exception as exc:
            diag["imports"][mod_path] = str(exc)[:120]
            log.error("Import %s FAILED: %s", mod_path, exc)

    # 4. Report to Phoenix
    try:
        from report_to_phoenix import report_signal_event
        failed_imports = {k: v for k, v in diag["imports"].items() if v != "ok"}
        await report_signal_event(config, "pipeline_started", {
            "redis_ping": diag["redis_ping"],
            "stream_key": stream_key,
            "stream_length": diag["stream_length"],
            "connector_id": connector_id,
            "import_errors": failed_imports if failed_imports else None,
            "pid": os.getpid(),
        })
        log.info("Startup diagnostic reported to Phoenix")
    except Exception as exc:
        log.warning("Failed to report startup diagnostic to Phoenix: %s", exc)

    # 5. Update shared state and write status file
    _pipeline_state["started_at"] = datetime.now(timezone.utc).isoformat()
    _pipeline_state["redis_connected"] = diag["redis_ping"]
    _pipeline_state["stream_key"] = stream_key

    return diag


async def process_signal(raw_signal: dict, config: dict) -> dict:
    """Process a single signal through the full pipeline in-process."""
    from decision_engine import _build_execution_params
    from parse_signal import parse as parse_signal

    steps: list[dict] = []
    reasoning: list[str] = []
    risk_params = config.get("risk_params", {})

    # Step 1: Parse
    parsed = parse_signal(raw_signal)
    steps.append({"step": "parse_signal", "status": "ok"})

    ticker = parsed.get("ticker")
    direction = parsed.get("direction")
    if not ticker:
        snippet = raw_signal.get("content", "")[:100]
        reasoning.append(f"No ticker found in signal: '{snippet}'")
        return _build_result("REJECT", "no_ticker", steps, reasoning, parsed,
                             source_message_id=raw_signal.get("message_id"))
    if not direction:
        reasoning.append(f"No trade direction found for {ticker}")
        return _build_result("REJECT", "no_direction", steps, reasoning, parsed,
                             source_message_id=raw_signal.get("message_id"))

    try:
        from market_session_gate import outside_rth_watchlist_payload

        gate = outside_rth_watchlist_payload(parsed, config, steps, reasoning)
        if gate:
            result = _build_result(
                "WATCHLIST",
                gate["reason"],
                steps,
                reasoning,
                parsed,
                gate["prediction"],
                None,
                source_message_id=raw_signal.get("message_id"),
            )
            result["market_status"] = gate["market_status"]
            result["execution"] = {"deferred": True, "reason": "outside_regular_session"}
            return result
    except Exception as exc:
        log.debug("market_session_gate skipped: %s", exc)

    # Step 2: Enrich
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

    # Step 3: Inference
    prediction = {"prediction": "SKIP", "confidence": 0.0, "pattern_matches": 0}
    source_channel = str(raw_signal.get("channel") or "").lower()
    ml_bypass = bool(source_channel and source_channel in _bypass_ml_channels())

    if ml_bypass:
        prediction = {
            "prediction": "TRADE",
            "confidence": 1.0,
            "model": "bypass:test_channel",
            "pattern_matches": 0,
            "bypass": True,
        }
        steps.append({"step": "inference", "status": "bypassed", "channel": source_channel})
        reasoning.append(f"Bypassed ML inference (channel='{source_channel}' is in BYPASS_ML_CHANNELS)")
    else:
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

    if not has_models and not ml_bypass:
        reasoning.append("No trained models available — adding to watchlist for observation")
        try:
            from robinhood_mcp_client import add_to_watchlist
            add_to_watchlist(ticker, config=config)
            steps.append({"step": "watchlist_add", "status": "ok", "ticker": ticker})
        except Exception as exc:
            steps.append({"step": "watchlist_add", "status": "skipped", "error": str(exc)[:120]})
        return _build_result(
            "WATCHLIST", "no_backtesting_data", steps, reasoning, parsed,
            prediction, None,
            source_message_id=raw_signal.get("message_id"),
        )

    # Step 4: Risk check
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
            return _build_result("REJECT", risk_result.get("rejection_reason", "risk_failed"),
                                 steps, reasoning, parsed, prediction, risk_result,
                                 source_message_id=raw_signal.get("message_id"))
        reasoning.append("Risk check passed")
    except Exception as e:
        steps.append({"step": "risk_check", "status": "failed", "error": str(e)[:200]})
        return _build_result("REJECT", "risk_check_error", steps, reasoning, parsed, prediction,
                             source_message_id=raw_signal.get("message_id"))

    # Step 5: TA confirmation
    ta_result = None
    try:
        from technical_analysis import analyze_ticker
        ta_result = analyze_ticker(ticker)
        steps.append({"step": "ta_confirmation", "status": "ok",
                       "verdict": ta_result.get("overall_verdict")})
        ta_verdict = ta_result.get("overall_verdict", "")
        ta_conf = ta_result.get("confidence", 0)
        if direction == "buy" and ta_verdict == "bearish" and ta_conf > 0.5:
            reasoning.append("TA strongly contradicts buy signal")
            return _build_result("REJECT", "ta_misalignment", steps, reasoning, parsed, prediction, risk_result,
                                 source_message_id=raw_signal.get("message_id"))
        if direction == "sell" and ta_verdict == "bullish" and ta_conf > 0.5:
            reasoning.append("TA strongly contradicts sell signal")
            return _build_result("REJECT", "ta_misalignment", steps, reasoning, parsed, prediction, risk_result,
                                 source_message_id=raw_signal.get("message_id"))
        reasoning.append(f"TA: {ta_verdict} (conf={ta_conf:.2f})")
    except Exception as e:
        steps.append({"step": "ta_confirmation", "status": "skipped", "error": str(e)[:200]})
        reasoning.append("TA check skipped")

    # Step 6: Model must say TRADE
    if prediction.get("prediction") != "TRADE":
        reasoning.append(f"Model says SKIP (confidence={prediction.get('confidence', 0):.3f})")
        return _build_result("REJECT", "model_skip", steps, reasoning, parsed, prediction, risk_result,
                             source_message_id=raw_signal.get("message_id"))

    # Step 7: Build execution params and approve
    exec_params = _build_execution_params(parsed, enriched, prediction, risk_params, ta_result)
    reasoning.append(f"APPROVED: {direction.upper()} {ticker}")
    result = _build_result("EXECUTE", None, steps, reasoning, parsed, prediction, risk_result,
                           source_message_id=raw_signal.get("message_id"))
    result["execution"] = exec_params
    return result


def _log_to_phoenix(decision: str, reason: str | None,
                    parsed: dict | None, prediction: dict | None,
                    source_message_id: str | None) -> None:
    """Best-effort log every decision to trade_signals via Phoenix API."""
    try:
        from log_trade_signal import log_signal
    except ImportError:
        return
    if not parsed or not parsed.get("ticker"):
        return
    canonical = {
        "execute": "executed", "reject": "rejected",
        "watchlist": "watchlist", "paper": "paper",
    }.get((decision or "").lower(), "rejected")
    try:
        log_signal(
            ticker=parsed["ticker"],
            direction=parsed.get("direction"),
            decision=canonical,
            predicted_prob=(prediction or {}).get("confidence"),
            model_confidence=(prediction or {}).get("confidence"),
            rejection_reason=reason,
            features={},
            source_message_id=source_message_id,
        )
    except Exception:
        pass


def _build_result(decision: str, reason: str | None, steps: list, reasoning: list,
                  parsed: dict | None = None, prediction: dict | None = None,
                  risk_result: dict | None = None,
                  source_message_id: str | None = None) -> dict:
    _log_to_phoenix(decision, reason, parsed, prediction, source_message_id)
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
        }
    if prediction:
        result["model_prediction"] = prediction
    if risk_result:
        result["risk_check"] = risk_result
    return result


async def _redis_signal_stream(config: dict):
    """Async generator yielding signal dicts from the Redis stream."""
    import os
    try:
        import redis.asyncio as aioredis
    except ImportError:
        log.error("redis-py not installed")
        return

    from discord_redis_consumer import CONSUMER_GROUP, _ensure_consumer_group

    redis_url = config.get("redis_url") or os.getenv("REDIS_URL", "redis://localhost:6379")
    connector_id = config.get("connector_id")
    channel_id = config.get("channel_id", connector_id)
    if not connector_id and not channel_id:
        log.error("config missing connector_id and channel_id")
        return

    primary_key = f"stream:channel:{connector_id}" if connector_id else None
    fallback_key = f"stream:channel:{channel_id}"
    try:
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
    except Exception as exc:
        log.error("Redis connect failed: %s", exc)
        return

    stream_key = primary_key or fallback_key
    if primary_key and primary_key != fallback_key:
        try:
            if await redis_client.xlen(primary_key) == 0 and await redis_client.xlen(fallback_key) > 0:
                stream_key = fallback_key
        except Exception:
            pass

    await _ensure_consumer_group(redis_client, stream_key)
    consumer_name = f"agent-{config.get('agent_id', 'default')}"
    log.info("Redis stream '%s' (consumer=%s)", stream_key, consumer_name)

    _pipeline_state["redis_connected"] = True
    _pipeline_state["stream_key"] = stream_key

    try:
        while True:
            try:
                result = await redis_client.xreadgroup(
                    CONSUMER_GROUP, consumer_name,
                    {stream_key: ">"}, count=50, block=5000,
                )
                if not result:
                    continue
                for _stream, entries in result:
                    for msg_id, data in entries:
                        yield {
                            "stream_id": msg_id,
                            "channel_id": data.get("channel_id", channel_id),
                            "channel": data.get("channel", ""),
                            "author": data.get("author", ""),
                            "content": data.get("content", ""),
                            "timestamp": data.get("timestamp", ""),
                            "message_id": data.get("message_id", ""),
                        }
                        await redis_client.xack(stream_key, CONSUMER_GROUP, msg_id)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Redis xread error: %s", exc, exc_info=True)
                await asyncio.sleep(2)
    finally:
        try:
            await redis_client.aclose()
        except Exception:
            pass


async def run_pipeline(config: dict) -> None:
    """Main pipeline loop — consume signals, process, execute."""
    from report_to_phoenix import report_heartbeat, report_signal_event

    # --- Startup diagnostics (visible on dashboard immediately) ---
    diag = await _startup_diagnostic(config)
    if not diag.get("redis_ping"):
        log.error("ABORTING: Redis not reachable. Pipeline cannot function.")
        return

    signals_processed = 0
    trades_today = 0
    log.info("Pipeline started, waiting for signals...")

    async def heartbeat_loop() -> None:
        while True:
            await asyncio.sleep(60)
            try:
                try:
                    from shared.utils.market_calendar import get_market_status

                    ms = get_market_status()
                    hb_extra = {
                        "market_session": ms["session"],
                        "market_regular_open": ms["regular_session_open"],
                        "market_summary": ms["summary"][:240],
                    }
                except Exception:
                    hb_extra = {}
                await report_heartbeat(config, {
                    "status": "listening",
                    "signals_processed": signals_processed,
                    "trades_today": trades_today,
                    **hb_extra,
                })
            except Exception as exc:
                log.warning("Heartbeat failed: %s", exc)

    asyncio.create_task(heartbeat_loop())

    async for signal in _redis_signal_stream(config):
        signals_processed += 1
        _pipeline_state["signals_processed"] = signals_processed
        _pipeline_state["last_signal_time"] = datetime.now(timezone.utc).isoformat()
        log.info("Signal #%d: %s", signals_processed, signal.get("content", "")[:80])

        signal_ts = signal.get("timestamp", "")
        if signal_ts:
            try:
                from dateutil.parser import isoparse
            except ImportError:
                from datetime import datetime as _dt
                isoparse = _dt.fromisoformat
            try:
                msg_time = isoparse(signal_ts)
                if msg_time.tzinfo is None:
                    msg_time = msg_time.replace(tzinfo=timezone.utc)
                age_seconds = (datetime.now(timezone.utc) - msg_time).total_seconds()
                if age_seconds > MAX_SIGNAL_AGE_SECONDS:
                    log.info("SKIP stale signal (age=%.0fs > %ds): %s",
                             age_seconds, MAX_SIGNAL_AGE_SECONDS,
                             signal.get("content", "")[:60])
                    continue
            except (ValueError, TypeError):
                pass

        try:
            await report_signal_event(config, "signal_received", {
                "content": signal.get("content", "")[:200],
                "author": signal.get("author", ""),
                "message_id": signal.get("message_id", ""),
            })
        except Exception as exc:
            log.warning("report_signal_event(signal_received) failed: %s", exc)

        try:
            decision = await process_signal(signal, config)
            decision = _json_safe(decision)
            decision["signal_raw"] = signal.get("content", "")

            ticker = decision.get("parsed_signal", {}).get("ticker", "?")
            direction = decision.get("parsed_signal", {}).get("direction", "?")

            try:
                await report_signal_event(config, "signal_decided", {
                    "ticker": ticker,
                    "decision": decision["decision"],
                    "reason": decision.get("reason", "")[:200],
                })
            except Exception as exc:
                log.warning("report_signal_event(signal_decided) failed: %s", exc)

            if decision["decision"] == "EXECUTE":
                trades_today += 1
                _pipeline_state["trades_today"] = trades_today
                log.info("EXECUTE: %s %s", direction, ticker)

                try:
                    from execute_trade import execute as execute_trade
                    config_path = str(Path(config.get("_config_path", "config.json")))
                    exec_result = execute_trade(decision, config_path)
                    log.info("Execution: %s", json.dumps(exec_result, default=str)[:300])

                    if direction in ("sell", "close", "trim"):
                        _route_sell_signal(ticker, signal, decision)
                except Exception as e:
                    log.error("Trade execution failed: %s", e, exc_info=True)
            elif decision["decision"] == "WATCHLIST":
                log.info("WATCHLIST (outside RTH or policy): %s — %s", ticker, decision.get("reason"))
                try:
                    import httpx as _httpx
                    api_url = config.get("phoenix_api_url", "http://localhost:8011")
                    async with _httpx.AsyncClient(timeout=5) as _wl_client:
                        await _wl_client.post(
                            f"{api_url}/api/v2/watchlist/lists",
                            json={"symbols": [ticker], "watchlist_name": "Agent Signals"},
                        )
                except Exception as _wl_err:
                    log.debug("Watchlist API sync failed: %s", _wl_err)
            else:
                log.info("REJECT: %s — %s", ticker, decision.get("reason"))
                if direction in ("sell", "close", "trim") and ticker:
                    _route_sell_signal(ticker, signal, decision)
        except Exception as e:
            log.error("Pipeline error: %s", e, exc_info=True)
            _pipeline_state["last_error"] = f"{e}"[:200]


def _route_sell_signal(ticker: str, raw_signal: dict, decision: dict) -> None:
    """Write a sell signal file for the position sub-agent."""
    registry_path = Path("position_registry.json")
    if not registry_path.exists():
        return
    try:
        registry = json.loads(registry_path.read_text())
    except Exception:
        return
    if ticker not in registry:
        return

    sell_dir = Path("positions") / ticker
    sell_dir.mkdir(parents=True, exist_ok=True)
    sell_signal = {
        "ticker": ticker,
        "signal_type": "sell",
        "content": raw_signal.get("content", ""),
        "author": raw_signal.get("author", ""),
        "timestamp": raw_signal.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "decision": decision.get("decision"),
        "reasoning": decision.get("reasoning", []),
    }
    (sell_dir / "sell_signal.json").write_text(json.dumps(sell_signal, indent=2, default=str))
    log.info("Sell signal routed for %s (file)", ticker)

    # Also POST to Phoenix API so in-process micro-agents receive the signal
    try:
        config_path = Path("config.json")
        if config_path.exists():
            cfg = json.loads(config_path.read_text())
            api_url = cfg.get("phoenix_api_url", "http://localhost:8011")
            agent_id = cfg.get("agent_id", "")
            if agent_id:
                import urllib.request
                req = urllib.request.Request(
                    f"{api_url}/api/v2/agents/{agent_id}/route-sell-signal",
                    data=json.dumps(sell_signal).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5)
                log.info("Sell signal routed for %s (API)", ticker)
    except Exception as e:
        log.warning("API sell-signal routing failed (non-fatal): %s", e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Live trading pipeline (hot loop)")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)
    config["_config_path"] = args.config

    asyncio.run(run_pipeline(config))


if __name__ == "__main__":
    main()
