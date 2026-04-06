"""Headline analyzer — scores social media signals against market data.

Cross-references signals with:
- Volume surge (yfinance)
- Recent price action
- Sentiment alignment

Usage:
    python headline_analyzer.py --signal reddit_signals.json --source reddit --output analysis.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def analyze(signals: list[dict], source: str) -> list[dict]:
    """Score and rank social signals against market confirmation."""
    analyzed: list[dict] = []

    for sig in signals:
        ticker = sig.get("ticker", "")
        if not ticker:
            continue

        result = {
            **sig,
            "source_type": source,
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
            "volume_check": False,
            "price_action_check": False,
            "overall_score": 0.0,
        }

        # Fetch market data
        try:
            import yfinance as yf
            data = yf.download(ticker, period="5d", progress=False)
            if not data.empty and len(data) >= 2:
                if hasattr(data.columns, "levels"):
                    data.columns = data.columns.get_level_values(0)
                avg_vol = float(data["Volume"].iloc[:-1].mean())
                cur_vol = float(data["Volume"].iloc[-1])
                vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0
                result["volume_ratio"] = round(vol_ratio, 2)
                result["volume_check"] = vol_ratio > 1.5

                price_change = (float(data["Close"].iloc[-1]) - float(data["Close"].iloc[-2])) / float(data["Close"].iloc[-2])
                result["price_change_1d_pct"] = round(price_change * 100, 2)
                result["price_action_check"] = abs(price_change) > 0.01
        except Exception as e:
            result["market_data_error"] = str(e)[:100]

        # Score
        score = 0.0
        sentiment = sig.get("sentiment", {})
        direction_text = sentiment.get("direction") or sig.get("direction") or "neutral"

        # Source engagement
        if source == "reddit":
            mention_count = sig.get("mention_count", 1)
            score += min(mention_count / 5, 0.30)
        else:  # twitter
            engagement = sig.get("likes", 0) + sig.get("retweets", 0) * 2
            score += min(engagement / 200, 0.30)
            if sig.get("is_breaking"):
                score += 0.10

        # Volume confirmation
        if result.get("volume_check"):
            score += 0.25

        # Sentiment-price alignment
        price_change = result.get("price_change_1d_pct", 0) or 0
        if direction_text == "bullish" and price_change > 0:
            score += 0.20
        elif direction_text == "bearish" and price_change < 0:
            score += 0.20

        # Sentiment confidence
        score += sentiment.get("confidence", 0) * 0.15

        result["overall_score"] = round(min(score, 1.0), 3)
        result["direction"] = ("buy" if direction_text == "bullish"
                               else "sell" if direction_text == "bearish"
                               else "neutral")
        result["content"] = sig.get("title") or sig.get("content", "")[:200]

        if result["overall_score"] >= 0.4 and result["direction"] != "neutral":
            analyzed.append(result)

    analyzed.sort(key=lambda r: r["overall_score"], reverse=True)
    return analyzed


def main():
    parser = argparse.ArgumentParser(description="Headline analyzer")
    parser.add_argument("--signal", required=True)
    parser.add_argument("--source", default="reddit")
    parser.add_argument("--output", default="analysis.json")
    args = parser.parse_args()

    signals = json.loads(Path(args.signal).read_text())
    if not isinstance(signals, list):
        signals = [signals]

    results = analyze(signals, args.source)
    Path(args.output).write_text(json.dumps(results, indent=2, default=str))
    print(f"Analyzed {len(results)} viable signals → {args.output}")


if __name__ == "__main__":
    main()
