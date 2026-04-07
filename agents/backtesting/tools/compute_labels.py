"""T1: Multi-head label panel.

Augments transformed.parquet with supervised targets for every downstream
trade-intelligence model head:

    y_win            binary      (existing - reused)
    y_pnl_pct        regression  (existing - reused as column)
    y_mfe_atr        regression  Max Favorable Excursion / ATR14 - TP head (T3)
    y_mae_atr        regression  Max Adverse  Excursion / ATR14 - SL head (T3)
    y_hold_minutes   regression  Exit timing regressor (T4)
    y_exit_bucket    5-class     Exit timing classifier (T4)
    y_entry_slip_bps regression  Entry-buffer head (T5)   [NaN until live data]
    y_fill_60s       binary      Fillability head (T5)    [NaN until live data]

MFE/MAE are replayed from 5-minute yfinance bars between entry_time and
exit_time_final. ATR14 is computed on daily bars ending at entry_date.

Usage:
    python tools/compute_labels.py --input output/transformed.parquet \
                                   --output output/transformed.parquet
"""
from __future__ import annotations

import argparse
from pathlib import Path
import math

import numpy as np
import pandas as pd


EXIT_BUCKETS = ["lt_5m", "5_30m", "30m_2h", "2h_eod", "next_day"]


def _bucket_from_minutes(m: float) -> str:
    if not np.isfinite(m) or m < 0:
        return "5_30m"
    if m < 5:
        return "lt_5m"
    if m < 30:
        return "5_30m"
    if m < 120:
        return "30m_2h"
    if m < 390:  # one trading session ~6.5h
        return "2h_eod"
    return "next_day"


def _atr14(daily: pd.DataFrame) -> float:
    """True-range based ATR14 on the last 15 daily bars. Returns NaN on failure."""
    if daily is None or len(daily) < 15:
        return float("nan")
    h = daily["High"].astype(float).values
    l = daily["Low"].astype(float).values
    c = daily["Close"].astype(float).values
    tr = np.maximum.reduce([
        h[1:] - l[1:],
        np.abs(h[1:] - c[:-1]),
        np.abs(l[1:] - c[:-1]),
    ])
    if len(tr) < 14:
        return float("nan")
    return float(np.mean(tr[-14:]))


def _replay_mfe_mae(bars: pd.DataFrame, entry_time: pd.Timestamp,
                    exit_time: pd.Timestamp, entry_price: float,
                    side: str) -> tuple[float, float]:
    """Return (MFE, MAE) in absolute price units over the hold window.

    MFE is the largest favorable move from entry; MAE is the largest adverse.
    Both are >= 0. Returns (nan, nan) when bars are missing.
    """
    if bars is None or len(bars) == 0 or not np.isfinite(entry_price):
        return float("nan"), float("nan")
    try:
        window = bars.loc[(bars.index >= entry_time) & (bars.index <= exit_time)]
    except Exception:
        return float("nan"), float("nan")
    if len(window) == 0:
        return float("nan"), float("nan")

    highs = window["High"].astype(float).values
    lows = window["Low"].astype(float).values
    if side == "long":
        mfe = float(np.max(highs) - entry_price)
        mae = float(entry_price - np.min(lows))
    else:  # short
        mfe = float(entry_price - np.min(lows))
        mae = float(np.max(highs) - entry_price)
    return max(0.0, mfe), max(0.0, mae)


def _fetch_bars(ticker: str, start: pd.Timestamp, end: pd.Timestamp,
                interval: str, cache: dict) -> pd.DataFrame | None:
    """Cached yfinance download. Silently returns None on failure."""
    key = (ticker, interval, start.date(), end.date())
    if key in cache:
        return cache[key]
    try:
        import yfinance as yf
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=(end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            interval=interval,
            progress=False,
            auto_adjust=False,
        )
        if df is None or df.empty:
            cache[key] = None
            return None
        # Flatten multiindex columns from some yf responses
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        cache[key] = df
        return df
    except Exception:
        cache[key] = None
        return None


def compute_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with y_* label columns added."""
    df = df.copy()
    n = len(df)

    y_win = df.get("is_profitable")
    if y_win is None:
        df["y_win"] = 0
    else:
        df["y_win"] = y_win.astype(int)

    df["y_pnl_pct"] = df.get("pnl_pct", pd.Series([np.nan] * n)).astype(float)

    mfe_atr = np.full(n, np.nan)
    mae_atr = np.full(n, np.nan)
    hold_min = np.full(n, np.nan)
    bucket = ["5_30m"] * n

    if n == 0:
        df["y_mfe_atr"] = mfe_atr
        df["y_mae_atr"] = mae_atr
        df["y_hold_minutes"] = hold_min
        df["y_exit_bucket"] = bucket
        df["y_entry_slip_bps"] = np.nan
        df["y_fill_60s"] = np.nan
        return df

    entry_t = pd.to_datetime(df["entry_time"], utc=True, errors="coerce")
    exit_t = pd.to_datetime(df.get("exit_time_final"), utc=True, errors="coerce")

    intraday_cache: dict = {}
    daily_cache: dict = {}

    for i in range(n):
        et = entry_t.iloc[i]
        xt = exit_t.iloc[i]
        if pd.isna(et) or pd.isna(xt):
            continue

        minutes = (xt - et).total_seconds() / 60.0
        if minutes < 0:
            continue
        hold_min[i] = minutes
        bucket[i] = _bucket_from_minutes(minutes)

        ticker = str(df.iloc[i].get("ticker") or "").upper()
        if not ticker:
            continue

        side = str(df.iloc[i].get("side") or "long").lower()
        entry_price = df.iloc[i].get("entry_price")
        try:
            entry_price = float(entry_price)
        except Exception:
            continue
        if not np.isfinite(entry_price):
            continue

        # Daily bars for ATR14 (21 trading days before entry is plenty)
        daily = _fetch_bars(
            ticker,
            et - pd.Timedelta(days=35),
            et,
            "1d",
            daily_cache,
        )
        atr = _atr14(daily)
        if not np.isfinite(atr) or atr <= 0:
            continue

        # Intraday bars for MFE/MAE replay. yfinance 5m only works ~60 days back,
        # fall back to 1h then 1d for older trades.
        age_days = (pd.Timestamp.utcnow() - et).days
        if age_days < 55:
            interval = "5m"
        elif age_days < 700:
            interval = "1h"
        else:
            interval = "1d"

        bars = _fetch_bars(ticker, et - pd.Timedelta(hours=1),
                           xt + pd.Timedelta(hours=1), interval, intraday_cache)
        mfe, mae = _replay_mfe_mae(bars, et, xt, entry_price, side)
        if np.isfinite(mfe):
            mfe_atr[i] = mfe / atr
        if np.isfinite(mae):
            mae_atr[i] = mae / atr

    df["y_mfe_atr"] = mfe_atr
    df["y_mae_atr"] = mae_atr
    df["y_hold_minutes"] = hold_min
    df["y_exit_bucket"] = bucket
    # Slippage + fillability require live execution data (T5/T8 will populate).
    df["y_entry_slip_bps"] = np.nan
    df["y_fill_60s"] = np.nan
    return df


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    df = pd.read_parquet(in_path)

    if not args.force and "y_mfe_atr" in df.columns and df["y_mfe_atr"].notna().any():
        print(f"Labels already present on {len(df)} rows — skipping (use --force to recompute)")
    else:
        print(f"Computing multi-head labels for {len(df)} trades...")
        df = compute_labels(df)

    cov = {
        "rows": len(df),
        "y_win_coverage": float(df["y_win"].notna().mean()) if len(df) else 0.0,
        "y_mfe_atr_coverage": float(df["y_mfe_atr"].notna().mean()) if len(df) else 0.0,
        "y_mae_atr_coverage": float(df["y_mae_atr"].notna().mean()) if len(df) else 0.0,
        "y_hold_minutes_coverage": float(df["y_hold_minutes"].notna().mean()) if len(df) else 0.0,
    }
    print(f"Label coverage: {cov}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    print(f"Saved {len(df)} rows with label panel to {out_path}")

    try:
        from report_to_phoenix import report_progress
        report_progress("compute_labels", f"Computed labels for {len(df)} trades", 18, cov)
    except Exception:
        pass


if __name__ == "__main__":
    main()
