"""Discover top trading patterns from enriched backtest data."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def discover_patterns(df: pd.DataFrame, n_patterns: int = 60) -> list[dict]:
    profitable = df[df["is_profitable"] == True]
    all_trades = df
    patterns = []

    n = len(df)
    min_bucket = max(3, n // 50)

    # Overall stats pattern (always included)
    if "is_profitable" in df.columns and len(df) > 0:
        patterns.append({
            "name": "overall_stats",
            "description": f"Aggregate stats across all {n} trades",
            "condition": "all trades",
            "win_rate": round(float(df["is_profitable"].mean()), 4),
            "sample_size": n,
            "avg_return": round(float(df["pnl_pct"].mean()), 4) if "pnl_pct" in df.columns else 0,
        })

    # Time-based patterns
    if "hour_of_day" in df.columns:
        for hour in range(7, 17):
            mask = all_trades["hour_of_day"] == hour
            subset = all_trades[mask]
            if len(subset) >= min_bucket:
                wr = subset["is_profitable"].mean()
                patterns.append({
                    "name": f"hour_{hour}_entry",
                    "condition": f"hour_of_day == {hour}",
                    "win_rate": round(float(wr), 4),
                    "sample_size": int(len(subset)),
                    "avg_return": round(float(subset["pnl_pct"].mean()), 4) if "pnl_pct" in subset else 0,
                })

    # RSI-based patterns
    if "rsi_14" in df.columns:
        non_null = all_trades["rsi_14"].dropna()
        if len(non_null) >= min_bucket:
            for lo, hi, label in [(0, 30, "oversold"), (30, 50, "weak"), (50, 70, "strong"), (70, 100, "overbought")]:
                mask = (all_trades["rsi_14"] >= lo) & (all_trades["rsi_14"] < hi)
                subset = all_trades[mask]
                if len(subset) >= min_bucket:
                    patterns.append({
                        "name": f"rsi_{label}",
                        "condition": f"rsi_14 between {lo} and {hi}",
                        "win_rate": round(float(subset["is_profitable"].mean()), 4),
                        "sample_size": int(len(subset)),
                        "avg_return": round(float(subset["pnl_pct"].mean()), 4) if "pnl_pct" in subset else 0,
                    })

    # VIX-based patterns
    if "vix_level" in df.columns:
        non_null = all_trades["vix_level"].dropna()
        if len(non_null) >= min_bucket:
            for lo, hi, label in [(0, 15, "low_vix"), (15, 25, "normal_vix"), (25, 40, "elevated_vix"), (40, 100, "extreme_vix")]:
                mask = (all_trades["vix_level"] >= lo) & (all_trades["vix_level"] < hi)
                subset = all_trades[mask]
                if len(subset) >= min_bucket:
                    patterns.append({
                        "name": f"vix_{label}",
                        "condition": f"vix_level between {lo} and {hi}",
                        "win_rate": round(float(subset["is_profitable"].mean()), 4),
                        "sample_size": int(len(subset)),
                        "avg_return": round(float(subset["pnl_pct"].mean()), 4) if "pnl_pct" in subset else 0,
                    })

    # Volume-based patterns
    if "volume_ratio" in df.columns:
        non_null = all_trades["volume_ratio"].dropna()
        if len(non_null) >= min_bucket:
            for lo, hi, label in [(0, 0.5, "low_vol"), (0.5, 1.5, "normal_vol"), (1.5, 3, "high_vol"), (3, 100, "extreme_vol")]:
                mask = (all_trades["volume_ratio"] >= lo) & (all_trades["volume_ratio"] < hi)
                subset = all_trades[mask]
                if len(subset) >= min_bucket:
                    patterns.append({
                        "name": f"volume_{label}",
                        "condition": f"volume_ratio between {lo} and {hi}",
                        "win_rate": round(float(subset["is_profitable"].mean()), 4),
                        "sample_size": int(len(subset)),
                        "avg_return": round(float(subset["pnl_pct"].mean()), 4) if "pnl_pct" in subset else 0,
                    })

    # Day-of-week patterns
    if "day_of_week" in df.columns:
        for dow, name in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday"]):
            mask = all_trades["day_of_week"] == dow
            subset = all_trades[mask]
            if len(subset) >= min_bucket:
                patterns.append({
                    "name": f"day_{name}",
                    "condition": f"day_of_week == {dow}",
                    "win_rate": round(float(subset["is_profitable"].mean()), 4),
                    "sample_size": int(len(subset)),
                    "avg_return": round(float(subset["pnl_pct"].mean()), 4) if "pnl_pct" in subset else 0,
                })

    # Profitable ticker patterns
    if "ticker" in df.columns and "is_profitable" in df.columns:
        for ticker, grp in all_trades.groupby("ticker"):
            if len(grp) >= min_bucket:
                patterns.append({
                    "name": f"ticker_{ticker}",
                    "condition": f"ticker == {ticker}",
                    "win_rate": round(float(grp["is_profitable"].mean()), 4),
                    "sample_size": int(len(grp)),
                    "avg_return": round(float(grp["pnl_pct"].mean()), 4) if "pnl_pct" in grp.columns else 0,
                })

    # Combination patterns: RSI oversold + high volume
    if "rsi_14" in df.columns and "volume_ratio" in df.columns:
        mask = (all_trades["rsi_14"] < 30) & (all_trades["volume_ratio"] > 1.5)
        subset = all_trades[mask]
        if len(subset) >= max(3, min_bucket // 2):
            patterns.append({
                "name": "rsi_oversold_high_volume",
                "condition": "rsi_14 < 30 AND volume_ratio > 1.5",
                "win_rate": round(float(subset["is_profitable"].mean()), 4),
                "sample_size": int(len(subset)),
                "avg_return": round(float(subset["pnl_pct"].mean()), 4) if "pnl_pct" in subset else 0,
            })

    # MACD cross + trend patterns
    if "macd_cross_up" in df.columns and "above_all_sma" in df.columns:
        mask = (all_trades["macd_cross_up"] == True) & (all_trades["above_all_sma"] == True)
        subset = all_trades[mask]
        if len(subset) >= max(3, min_bucket // 2):
            patterns.append({
                "name": "macd_cross_bullish_trend",
                "condition": "macd_cross_up == True AND above_all_sma == True",
                "win_rate": round(float(subset["is_profitable"].mean()), 4),
                "sample_size": int(len(subset)),
                "avg_return": round(float(subset["pnl_pct"].mean()), 4) if "pnl_pct" in subset else 0,
            })

    # Score and sort: weight win_rate by log of sample size
    for p in patterns:
        p["weight"] = p["win_rate"] * np.log1p(p["sample_size"])

    patterns.sort(key=lambda p: p["weight"], reverse=True)
    return patterns[:n_patterns]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    data_dir = Path(args.data)
    df = pd.read_parquet(data_dir / "enriched.parquet")
    if len(df) == 0:
        with open(args.output, "w") as f:
            json.dump([], f, indent=2)
        print("Discovered 0 patterns (empty enriched data)")
        try:
            from report_to_phoenix import report_progress
            report_progress("patterns", "Pattern discovery complete", 80, {"pattern_count": 0})
        except Exception:
            pass
        return
    patterns = discover_patterns(df)

    with open(args.output, "w") as f:
        json.dump(patterns, f, indent=2)

    print(f"Discovered {len(patterns)} patterns")
    for p in patterns[:10]:
        print(f"  {p['name']}: win_rate={p['win_rate']:.2%} (n={p['sample_size']})")
    try:
        from report_to_phoenix import report_progress
        report_progress("patterns", "Pattern discovery complete", 80, {
            "pattern_count": len(patterns),
            "patterns": patterns,
        })
    except Exception:
        pass


if __name__ == "__main__":
    main()
