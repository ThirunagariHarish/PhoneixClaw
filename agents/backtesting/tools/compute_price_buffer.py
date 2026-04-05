"""Compute optimal price buffers from backtesting data.

Analyses the price drift between signal timestamp and various latency
windows (30s, 60s, 120s) to determine how much prices typically move
before an order can be placed.  The 75th-percentile drift becomes the
recommended buffer so that limit orders still fill even with latency.

Usage:
    python compute_price_buffer.py \
        --data output/enriched.parquet \
        --output output/models/price_buffers.json
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
log = logging.getLogger(__name__)


def _percentile(arr, pct):
    if len(arr) == 0:
        return 0.0
    return float(np.percentile(arr, pct))


def compute_buffers(data_path: str, output_path: str):
    try:
        import pandas as pd
    except ImportError:
        log.error("pandas is required: pip install pandas")
        return

    df = pd.read_parquet(data_path)
    log.info("Loaded %d trades from %s", len(df), data_path)

    required = {"entry_price", "ticker"}
    if not required.issubset(df.columns):
        log.error("Missing columns: %s", required - set(df.columns))
        return

    try:
        import yfinance as yf
    except ImportError:
        yf = None
        log.warning("yfinance not available — using synthetic drift estimates")

    all_drifts: list[float] = []
    ticker_drifts: dict[str, list[float]] = {}

    if "price_at_30s" in df.columns and "price_at_60s" in df.columns:
        log.info("Using pre-computed price drift columns")
        for _, row in df.iterrows():
            ticker = row["ticker"]
            entry = row["entry_price"]
            if entry <= 0:
                continue
            if ticker not in ticker_drifts:
                ticker_drifts[ticker] = []

            for col in ["price_at_30s", "price_at_60s", "price_at_120s"]:
                if col in df.columns and pd.notna(row.get(col)):
                    drift = abs(row[col] - entry) / entry * 100
                    all_drifts.append(drift)
                    ticker_drifts[ticker].append(drift)
    else:
        log.info("No drift columns found — estimating from volatility")
        for ticker, group in df.groupby("ticker"):
            prices = group["entry_price"].values
            if len(prices) < 5:
                continue
            returns = np.diff(prices) / prices[:-1]
            vol = np.std(returns) if len(returns) > 1 else 0.01

            for _ in range(len(group)):
                drift_30s = abs(np.random.normal(0, vol * np.sqrt(30 / 3600))) * 100
                drift_60s = abs(np.random.normal(0, vol * np.sqrt(60 / 3600))) * 100
                drift_120s = abs(np.random.normal(0, vol * np.sqrt(120 / 3600))) * 100
                all_drifts.extend([drift_30s, drift_60s, drift_120s])
                if ticker not in ticker_drifts:
                    ticker_drifts[ticker] = []
                ticker_drifts[ticker].extend([drift_30s, drift_60s, drift_120s])

    if not all_drifts:
        log.warning("No drift data computed — using default 0.5%% buffer")
        result = {
            "aggregate": {"p50": 0.3, "p75": 0.5, "p90": 0.8, "p95": 1.0, "recommended_buffer_pct": 0.5},
            "per_ticker": {},
            "total_samples": 0,
        }
    else:
        drifts = np.array(all_drifts)
        aggregate = {
            "p50": round(_percentile(drifts, 50), 4),
            "p75": round(_percentile(drifts, 75), 4),
            "p90": round(_percentile(drifts, 90), 4),
            "p95": round(_percentile(drifts, 95), 4),
            "recommended_buffer_pct": round(_percentile(drifts, 75), 4),
            "mean": round(float(np.mean(drifts)), 4),
            "std": round(float(np.std(drifts)), 4),
        }

        per_ticker = {}
        for ticker, dlist in ticker_drifts.items():
            if len(dlist) < 3:
                continue
            arr = np.array(dlist)
            per_ticker[ticker] = {
                "p50": round(_percentile(arr, 50), 4),
                "p75": round(_percentile(arr, 75), 4),
                "p90": round(_percentile(arr, 90), 4),
                "recommended_buffer_pct": round(_percentile(arr, 75), 4),
                "sample_count": len(dlist),
            }

        result = {
            "aggregate": aggregate,
            "per_ticker": per_ticker,
            "total_samples": len(all_drifts),
        }

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(result, f, indent=2)

    log.info("Price buffers written to %s", output_path)
    log.info("Aggregate recommended buffer: %.4f%%", result["aggregate"]["recommended_buffer_pct"])
    log.info("Per-ticker buffers computed for %d tickers", len(result.get("per_ticker", {})))


def main():
    parser = argparse.ArgumentParser(description="Compute optimal price buffers from backtesting data")
    parser.add_argument("--data", required=True, help="Path to enriched.parquet")
    parser.add_argument("--output", required=True, help="Output path for price_buffers.json")
    args = parser.parse_args()
    compute_buffers(args.data, args.output)


if __name__ == "__main__":
    main()
