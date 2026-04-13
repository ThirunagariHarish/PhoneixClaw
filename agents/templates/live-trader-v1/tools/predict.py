"""Call the Phoenix inference service for ML predictions.

Replaces the old local inference.py that loaded models from disk.
Communicates with the inference service via HTTP.

Usage:
    python3 tools/predict.py --ticker PLTR --agent-id UUID --signal-features '{"direction":"BUY"}' --config config.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [predict] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

INFERENCE_TIMEOUT = 20
FALLBACK_PREDICTION = {
    "prediction": "SKIP",
    "confidence": 0.0,
    "pattern_matches": 0,
    "reasoning": "inference service unavailable",
}


def predict(
    ticker: str,
    agent_id: str,
    signal_features: dict,
    inference_url: str,
    enriched_features: dict | None = None,
) -> dict:
    """Call the inference service and return prediction JSON.

    Falls back to a safe SKIP prediction when the service is unreachable.
    """
    payload: dict = {
        "ticker": ticker,
        "agent_id": agent_id,
        "signal_features": signal_features,
    }
    if enriched_features:
        payload["features"] = enriched_features

    url = f"{inference_url.rstrip('/')}/predict"
    try:
        resp = httpx.post(url, json=payload, timeout=INFERENCE_TIMEOUT)
        if resp.status_code >= 400:
            log.warning("Inference service returned %d: %s", resp.status_code, resp.text[:200])
            return {**FALLBACK_PREDICTION, "reasoning": f"inference_error_{resp.status_code}"}
        result = resp.json()
        log.info("Prediction: %s (confidence=%.3f)", result.get("prediction"), result.get("confidence", 0))
        return result
    except httpx.ConnectError as exc:
        log.warning("Cannot reach inference service at %s: %s", inference_url, exc)
        return {**FALLBACK_PREDICTION}
    except httpx.TimeoutException:
        log.warning("Inference service timed out after %ds", INFERENCE_TIMEOUT)
        return {**FALLBACK_PREDICTION, "reasoning": "inference service timeout"}
    except Exception as exc:
        log.warning("Inference request failed: %s", exc)
        return {**FALLBACK_PREDICTION, "reasoning": f"inference_error: {exc}"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Call inference service for prediction")
    parser.add_argument("--ticker", required=True, help="Stock ticker symbol")
    parser.add_argument("--agent-id", required=True, help="Agent UUID")
    parser.add_argument("--signal-features", required=True, help="JSON string of signal features")
    parser.add_argument("--config", default="config.json", help="Path to config.json")
    args = parser.parse_args()

    config: dict = {}
    config_path = Path(args.config)
    if config_path.exists():
        config = json.loads(config_path.read_text())

    inference_url = config.get("inference_service_url", "http://localhost:8045")
    agent_id = args.agent_id or config.get("agent_id", "")

    try:
        features = json.loads(args.signal_features)
    except json.JSONDecodeError:
        features = {"raw": args.signal_features}

    result = predict(
        ticker=args.ticker,
        agent_id=agent_id,
        signal_features=features,
        inference_url=inference_url,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
