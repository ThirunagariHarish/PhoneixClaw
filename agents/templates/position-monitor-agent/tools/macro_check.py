"""Macro environment check for position monitoring via FRED cached data.

Evaluates yield curve, VIX spikes, and consumer sentiment shifts
to provide macro-level exit urgency signals.

Usage:
    python macro_check.py --side buy --output macro.json
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np


def check_macro(side: str) -> dict:
    """Evaluate macro conditions for exit urgency."""
    result = {
        "side": side,
        "exit_urgency": 0,
        "signals": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    is_long = side == "buy"
    urgency = 0

    try:
        from shared.data.fred_client import get_fred_client
        client = get_fred_client()
        today = date.today()
        features = client.get_macro_features(today)

        # Yield curve inversion
        inverted = features.get("yield_curve_inverted", np.nan)
        if inverted == 1.0:
            result["signals"]["yield_curve"] = "inverted"
            if is_long:
                urgency += 10

        # Yield spread change (sharp move)
        spread_chg = features.get("yield_spread_change_5d", np.nan)
        if not np.isnan(spread_chg):
            result["signals"]["yield_spread_5d_change"] = round(spread_chg, 3)
            if is_long and spread_chg < -0.2:
                urgency += 5
                result["signals"]["yield_alert"] = "rapid_spread_compression"

        # Consumer sentiment drop
        sent_chg = features.get("consumer_sentiment_change", np.nan)
        if not np.isnan(sent_chg):
            result["signals"]["consumer_sentiment_change"] = round(sent_chg, 1)
            if is_long and sent_chg < -3:
                urgency += 5
                result["signals"]["sentiment_alert"] = "sharp_sentiment_drop"

        # Treasury yields (rising rates pressure equities)
        t10y = features.get("treasury_10y", np.nan)
        if not np.isnan(t10y):
            result["signals"]["treasury_10y"] = round(t10y, 2)

        # CPI acceleration
        cpi_yoy = features.get("cpi_yoy_change", np.nan)
        if not np.isnan(cpi_yoy) and cpi_yoy > 4.0:
            if is_long:
                urgency += 3
                result["signals"]["inflation_alert"] = f"elevated_cpi_yoy={cpi_yoy:.1f}%"

    except Exception as e:
        result["signals"]["fred_error"] = str(e)[:100]

    # VIX intraday check (from yfinance, not FRED — more real-time)
    try:
        import yfinance as yf
        vix = yf.download("^VIX", period="2d", interval="1d", progress=False)
        if not vix.empty:
            if hasattr(vix.columns, "levels"):
                vix.columns = vix.columns.get_level_values(0)
            vix_level = float(vix["Close"].iloc[-1])
            result["signals"]["vix_level"] = round(vix_level, 1)
            if len(vix) >= 2:
                vix_change = float((vix["Close"].iloc[-1] / vix["Close"].iloc[-2] - 1) * 100)
                result["signals"]["vix_change_pct"] = round(vix_change, 1)
                if is_long and vix_change > 15:
                    urgency += 20
                    result["signals"]["vix_spike"] = f"vix_spiked_{vix_change:.1f}%"
                elif is_long and vix_level > 30:
                    urgency += 10
                    result["signals"]["vix_elevated"] = f"vix_at_{vix_level:.1f}"
    except Exception:
        pass

    result["exit_urgency"] = min(urgency, 40)
    return result


def main():
    parser = argparse.ArgumentParser(description="Macro environment check for exit decisions")
    parser.add_argument("--side", required=True, choices=["buy", "sell"])
    parser.add_argument("--output", default="macro.json")
    args = parser.parse_args()

    result = check_macro(args.side)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
