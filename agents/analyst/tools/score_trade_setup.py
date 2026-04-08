"""Score and aggregate tool signals into a confidence score."""
from __future__ import annotations

import argparse
import json
import logging

logger = logging.getLogger(__name__)

_SIGNAL_MAP = {"bullish": 1, "bearish": -1, "neutral": 0}


def score_trade_setup(
    ticker: str,
    persona_config: dict,
    chart_signal: dict,
    options_signal: dict,
    sentiment_signal: dict,
    dark_pool_signal: dict | None = None,
) -> dict:
    """Aggregate tool signals into a 0-100 confidence score.

    Uses persona tool_weights to weight each signal's contribution.
    Returns confidence, recommendation, breakdown, and signals_used.

    Args:
        ticker: Stock ticker (for logging).
        persona_config: Dict with 'tool_weights' and 'signal_filters'.
        chart_signal: Output from analyze_chart().
        options_signal: Output from scan_options_flow().
        sentiment_signal: Output from get_news_sentiment().
        dark_pool_signal: Optional dark pool signal dict.

    Returns:
        Dict with confidence (0-100), recommendation, breakdown, signals_used, above_threshold.
    """
    tool_weights: dict[str, float] = persona_config.get("tool_weights", {
        "chart": 0.25, "options_flow": 0.25, "dark_pool": 0.25, "sentiment": 0.25,
    })
    min_threshold: int = persona_config.get("min_confidence_threshold", 60)

    chart_dir = _SIGNAL_MAP.get(chart_signal.get("signal", "neutral"), 0)
    options_dir = _SIGNAL_MAP.get(options_signal.get("signal", "neutral"), 0)
    sentiment_dir = _SIGNAL_MAP.get(sentiment_signal.get("signal", "neutral"), 0)
    dark_pool_dir = 0
    if dark_pool_signal:
        dark_pool_dir = _SIGNAL_MAP.get(dark_pool_signal.get("signal", "neutral"), 0)

    signals_used: list[str] = []
    if chart_dir != 0:
        signals_used.append("chart")
    if options_dir != 0:
        signals_used.append("options_flow")
    if sentiment_dir != 0:
        signals_used.append("sentiment")
    if dark_pool_dir != 0:
        signals_used.append("dark_pool")

    w_chart = tool_weights.get("chart", 0.25)
    w_options = tool_weights.get("options_flow", 0.25)
    w_dark = tool_weights.get("dark_pool", 0.25)
    w_sentiment = tool_weights.get("sentiment", 0.25)

    weighted_score = (
        chart_dir * w_chart
        + options_dir * w_options
        + sentiment_dir * w_sentiment
        + dark_pool_dir * w_dark
    )

    # Map -1→0, 0→50, 1→100
    confidence = int((weighted_score + 1) * 50)
    confidence = max(0, min(100, confidence))

    if confidence >= min_threshold:
        recommendation = "buy"
    elif confidence <= (100 - min_threshold):
        recommendation = "sell"
    else:
        recommendation = "neutral"

    above_threshold = confidence >= min_threshold or confidence <= (100 - min_threshold)

    breakdown = {
        "chart": round(chart_dir * w_chart * 50, 2),
        "options_flow": round(options_dir * w_options * 50, 2),
        "sentiment": round(sentiment_dir * w_sentiment * 50, 2),
        "dark_pool": round(dark_pool_dir * w_dark * 50, 2),
    }

    return {
        "confidence": confidence,
        "recommendation": recommendation,
        "breakdown": breakdown,
        "signals_used": signals_used,
        "above_threshold": above_threshold,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score a trade setup")
    parser.add_argument("--ticker", default="AAPL")
    parser.add_argument("--chart-signal", default='{"signal":"bullish"}')
    parser.add_argument("--options-signal", default='{"signal":"neutral"}')
    parser.add_argument("--sentiment-signal", default='{"signal":"bullish"}')
    parser.add_argument(
        "--persona-config",
        default='{"tool_weights":{"chart":0.5,"options_flow":0.3,"dark_pool":0.1,"sentiment":0.1},'
                '"min_confidence_threshold":70}',
    )
    args = parser.parse_args()

    result = score_trade_setup(
        ticker=args.ticker,
        persona_config=json.loads(args.persona_config),
        chart_signal=json.loads(args.chart_signal),
        options_signal=json.loads(args.options_signal),
        sentiment_signal=json.loads(args.sentiment_signal),
    )
    print(json.dumps(result, indent=2))
