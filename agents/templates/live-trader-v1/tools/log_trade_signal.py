"""Log a trade signal decision to Phoenix API.

Called by decision_engine.py after every decision (executed, rejected,
watchlist, paper). At EOD, the scheduler enriches these with outcome prices
and feeds them back into the next training cycle.

Usage (from Python):
    from log_trade_signal import log_signal
    log_signal(
        ticker="AAPL",
        direction="buy",
        decision="rejected",
        predicted_prob=0.58,
        model_confidence=0.52,
        rejection_reason="below_threshold",
        features={...},
    )

Usage (CLI):
    python log_trade_signal.py --ticker AAPL --direction buy --decision rejected \
        --reason below_threshold --features features.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _api_config() -> dict:
    cfg_path = Path("config.json")
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            return {
                "url": cfg.get("phoenix_api_url") or os.getenv("PHOENIX_API_URL", ""),
                "key": cfg.get("phoenix_api_key", ""),
                "agent_id": cfg.get("agent_id", ""),
            }
        except Exception:
            pass
    return {
        "url": os.getenv("PHOENIX_API_URL", ""),
        "key": os.getenv("PHOENIX_API_KEY", ""),
        "agent_id": os.getenv("AGENT_ID", ""),
    }


# Keys we want to persist in features (keep the snapshot small and stable)
KEY_FEATURES = [
    "rsi_14", "rsi_7", "macd_histogram", "bb_position", "atr_pct",
    "vix_level", "volume_ratio_20", "sma_20_50_cross", "above_all_sma",
    "return_1d", "return_5d", "return_20d",
    "sentiment_score", "sentiment_bullish",
    "hour_of_day", "day_of_week", "is_friday", "is_power_hour",
    "days_to_fomc", "days_to_earnings", "is_opex_week",
    "gex_value", "iv_rank", "options_put_call_ratio",
    "signal_price", "entry_price",
    "market_regular_session_open", "market_extended_session_open", "market_session",
    "market_status_label", "market_is_trading_day", "market_next_regular_open_et",
]


def _sanitize_features(features: dict) -> dict:
    """Pick the key features + cast numpy to Python types for JSON."""
    sanitized = {}
    for k in KEY_FEATURES:
        if k not in features:
            continue
        v = features[k]
        try:
            if v is None:
                continue
            if isinstance(v, bool):
                sanitized[k] = bool(v)
            elif isinstance(v, (int,)):
                sanitized[k] = int(v)
            elif isinstance(v, float):
                import math
                if not math.isnan(v) and not math.isinf(v):
                    sanitized[k] = round(float(v), 6)
            else:
                lim = 500 if k.startswith("market_") else 50
                sanitized[k] = str(v)[:lim]
        except Exception:
            continue
    return sanitized


def log_signal(
    ticker: str,
    direction: str | None,
    decision: str,
    predicted_prob: float | None = None,
    model_confidence: float | None = None,
    rejection_reason: str | None = None,
    features: dict | None = None,
    signal_source: str = "discord",
    source_message_id: str | None = None,
) -> dict:
    """POST a trade signal to Phoenix API. Non-blocking on failure."""
    api = _api_config()
    if not api["url"] or not api["agent_id"]:
        return {"logged": False, "reason": "no api config"}

    payload = {
        "agent_id": api["agent_id"],
        "ticker": ticker,
        "direction": direction,
        "signal_source": signal_source,
        "source_message_id": source_message_id,
        "predicted_prob": predicted_prob,
        "model_confidence": model_confidence,
        "decision": decision,
        "rejection_reason": rejection_reason,
        "features": _sanitize_features(features or {}),
    }

    try:
        import httpx
        resp = httpx.post(
            f"{api['url']}/api/v2/trade-signals",
            headers={"X-Agent-Key": api["key"]},
            json=payload,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return {"logged": True, "id": resp.json().get("id")}
        return {"logged": False, "status": resp.status_code, "error": resp.text[:200]}
    except Exception as exc:
        return {"logged": False, "error": str(exc)[:200]}


def main():
    parser = argparse.ArgumentParser(description="Log a trade signal to Phoenix API")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--direction", default=None)
    parser.add_argument("--decision", required=True,
                        choices=["executed", "rejected", "watchlist", "paper"])
    parser.add_argument("--predicted-prob", type=float, default=None)
    parser.add_argument("--confidence", type=float, default=None)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--features", default=None, help="Path to JSON with features")
    parser.add_argument("--signal-source", default="discord")
    parser.add_argument("--source-message-id", default=None)
    args = parser.parse_args()

    features = {}
    if args.features and Path(args.features).exists():
        try:
            features = json.loads(Path(args.features).read_text())
        except Exception:
            pass

    result = log_signal(
        ticker=args.ticker,
        direction=args.direction,
        decision=args.decision,
        predicted_prob=args.predicted_prob,
        model_confidence=args.confidence,
        rejection_reason=args.reason,
        features=features,
        signal_source=args.signal_source,
        source_message_id=args.source_message_id,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
