"""Unusual Whales signal generator — scores flow alerts and produces trade signals.

Usage:
    python uw_signal_generator.py --input flow_data.json --output signals.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _get_config() -> dict:
    cfg_path = Path("config.json")
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def score_signals(flow_data: dict, config: dict) -> list[dict]:
    """Score and rank flow alerts into actionable signals."""
    signals = []
    risk = config.get("risk_params", {})
    min_premium = risk.get("min_premium", 100_000)
    min_vol_oi_ratio = risk.get("min_vol_oi_ratio", 3.0)

    for alert in flow_data.get("flow_alerts", []):
        ticker = alert.get("ticker", "")
        premium = alert.get("premium", 0)
        volume = alert.get("volume", 0)
        open_interest = alert.get("open_interest", 1) or 1
        option_type = alert.get("option_type", "").upper()
        is_sweep = alert.get("is_sweep", False)

        score = 0.0
        reasons = []

        # Premium tier
        if premium >= 500_000:
            score += 0.35
            reasons.append("premium>$500K")
        elif premium >= min_premium:
            score += 0.20
            reasons.append(f"premium>${min_premium / 1000:.0f}K")
        else:
            continue  # Below minimum, skip

        # Volume / OI
        vol_oi = volume / max(open_interest, 1)
        if vol_oi >= min_vol_oi_ratio * 2:
            score += 0.30
            reasons.append(f"vol/OI={vol_oi:.1f}x (extreme)")
        elif vol_oi >= min_vol_oi_ratio:
            score += 0.15
            reasons.append(f"vol/OI={vol_oi:.1f}x")
        else:
            continue

        # Sweep prioritization
        if is_sweep:
            score += 0.20
            reasons.append("sweep order")

        # Direction inference
        if option_type == "CALL":
            direction = "buy"
        elif option_type == "PUT":
            direction = "sell"
        else:
            direction = "neutral"

        if direction == "neutral":
            continue

        signals.append({
            "ticker": ticker,
            "direction": direction,
            "option_type": option_type.lower(),
            "score": round(min(score, 1.0), 3),
            "premium": premium,
            "volume": volume,
            "open_interest": open_interest,
            "vol_oi_ratio": round(vol_oi, 2),
            "is_sweep": is_sweep,
            "strike": alert.get("strike"),
            "expiry": alert.get("expiry"),
            "reasons": reasons,
            "content": (f"${ticker} {option_type} unusual flow: ${premium:,.0f} premium, "
                        f"{vol_oi:.1f}x vol/OI{' (SWEEP)' if is_sweep else ''}"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # Sort by score descending
    signals.sort(key=lambda s: s["score"], reverse=True)

    # Deduplicate by ticker (keep highest score)
    seen = set()
    deduped = []
    for s in signals:
        if s["ticker"] not in seen:
            seen.add(s["ticker"])
            deduped.append(s)

    return deduped


def main():
    parser = argparse.ArgumentParser(description="UW signal generator")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="signals.json")
    args = parser.parse_args()

    flow_data = json.loads(Path(args.input).read_text())
    config = _get_config()
    signals = score_signals(flow_data, config)

    Path(args.output).write_text(json.dumps(signals, indent=2, default=str))
    print(f"Generated {len(signals)} signals → {args.output}")
    if signals:
        print(f"  Top: ${signals[0]['ticker']} ({signals[0]['direction']}) score={signals[0]['score']}")


if __name__ == "__main__":
    main()
