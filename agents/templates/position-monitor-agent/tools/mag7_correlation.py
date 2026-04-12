"""MAG-7 correlation tracker for position monitoring.

Tracks AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA. If MAG-7 moves
strongly against the position direction, increases exit urgency.

Usage:
    python mag7_correlation.py --side buy --output mag7.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

MAG7 = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"]

# Position ticker -> sector ETF for correlation breakdown
TICKER_SECTOR_ETF: dict[str, str] = {
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "XLK", "GOOGL": "XLC", "META": "XLC",
    "AMZN": "XLY", "TSLA": "XLY", "AVGO": "XLK", "CRM": "XLK", "ADBE": "XLK",
    "JPM": "XLF", "BAC": "XLF", "WFC": "XLF", "GS": "XLF", "MS": "XLF",
    "XOM": "XLE", "CVX": "XLE", "COP": "XLE",
    "UNH": "XLV", "JNJ": "XLV", "PFE": "XLV", "ABBV": "XLV", "LLY": "XLV",
    "CAT": "XLI", "HON": "XLI", "UPS": "XLI", "BA": "XLI",
}


def check_mag7(side: str, ticker: str | None = None) -> dict:
    """Check MAG-7 movement vs the position direction; optional sector correlation breakdown."""
    result = {
        "side": side,
        "ticker": ticker,
        "exit_urgency": 0,
        "mag7_changes": {},
        "spy_change_pct": None,
        "qqq_change_pct": None,
        "direction": "neutral",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        import yfinance as yf

        # Use SPY and QQQ as fast proxy + each MAG-7 stock
        tickers = ["SPY", "QQQ"] + MAG7
        data = yf.download(tickers, period="2d", progress=False, group_by="ticker")
        if data.empty:
            return result

        changes = []
        for tk in tickers:
            try:
                if tk in data.columns.get_level_values(0):
                    df = data[tk]
                else:
                    df = data
                if len(df) >= 2 and "Close" in df.columns:
                    last = float(df["Close"].iloc[-1])
                    prev = float(df["Close"].iloc[-2])
                    pct = (last - prev) / prev * 100 if prev > 0 else 0
                    if tk == "SPY":
                        result["spy_change_pct"] = round(pct, 2)
                    elif tk == "QQQ":
                        result["qqq_change_pct"] = round(pct, 2)
                    else:
                        result["mag7_changes"][tk] = round(pct, 2)
                        changes.append(pct)
            except (KeyError, IndexError):
                continue

        # Average MAG-7 change
        if changes:
            avg_mag7 = sum(changes) / len(changes)
            result["avg_mag7_change_pct"] = round(avg_mag7, 2)
            result["direction"] = "bullish" if avg_mag7 > 0 else "bearish"

            # Score exit urgency
            if side == "buy" and avg_mag7 < -1.0:
                result["exit_urgency"] += 20
                result["alert"] = f"MAG-7 selling off ({avg_mag7:.1f}%) while you're long"
            elif side == "sell" and avg_mag7 > 1.0:
                result["exit_urgency"] += 20
                result["alert"] = f"MAG-7 rallying ({avg_mag7:.1f}%) while you're short"

        # Tech-heavy QQQ check
        qqq = result.get("qqq_change_pct") or 0
        if side == "buy" and qqq < -1.5:
            result["exit_urgency"] += 10
        elif side == "sell" and qqq > 1.5:
            result["exit_urgency"] += 10

        # Cross-asset: treasury (TLT) and gold (GLD) moves
        for asset, name in [("TLT", "treasury"), ("GLD", "gold")]:
            try:
                asset_data = yf.download(asset, period="2d", progress=False)
                if not asset_data.empty and len(asset_data) >= 2:
                    if hasattr(asset_data.columns, "levels"):
                        asset_data.columns = asset_data.columns.get_level_values(0)
                    last = float(asset_data["Close"].iloc[-1])
                    prev = float(asset_data["Close"].iloc[-2])
                    pct = (last - prev) / prev * 100 if prev > 0 else 0
                    result[f"{name}_change_pct"] = round(pct, 2)
                    # Flight to safety: TLT up + equities down = risk-off
                    if name == "treasury" and side == "buy" and pct > 1.0:
                        result["exit_urgency"] += 8
                        result.setdefault("alerts", []).append(f"Flight to safety: TLT +{pct:.1f}%")
            except Exception:
                pass

        # Sector ETF vs underlying: rolling correlation breakdown
        if ticker:
            sym = ticker.upper().split(".")[0]
            sector_etf = TICKER_SECTOR_ETF.get(sym)
            if sector_etf:
                try:
                    import pandas as pd

                    d_t = yf.download(sym, period="60d", interval="1d", progress=False)
                    d_e = yf.download(sector_etf, period="60d", interval="1d", progress=False)
                    if not d_t.empty and not d_e.empty and len(d_t) >= 25 and len(d_e) >= 25:
                        if hasattr(d_t.columns, "levels"):
                            d_t.columns = d_t.columns.get_level_values(0)
                        if hasattr(d_e.columns, "levels"):
                            d_e.columns = d_e.columns.get_level_values(0)
                        ct = d_t["Close"].astype(float).pct_change().dropna()
                        ce = d_e["Close"].astype(float).pct_change().dropna()
                        joined = pd.concat([ct, ce], axis=1, join="inner").dropna()
                        joined.columns = ["t", "e"]
                        if len(joined) >= 30:
                            roll = joined["t"].rolling(20).corr(joined["e"])
                            roll = roll.dropna()
                            if len(roll) >= 20:
                                recent = float(roll.iloc[-5:].mean())
                                baseline = float(roll.iloc[-20:-5].mean())
                                result["sector_corr_recent"] = round(recent, 3)
                                result["sector_corr_baseline"] = round(baseline, 3)
                                if baseline > 0.35 and recent < baseline - 0.25:
                                    result["exit_urgency"] += 15
                                    result.setdefault("signals", {})["correlation_breakdown"] = (
                                        f"{sym} vs {sector_etf}: corr {recent:.2f} vs avg {baseline:.2f}"
                                    )
                except Exception as ex:
                    result.setdefault("signals", {})["sector_corr_error"] = str(ex)[:80]

    except Exception as e:
        result["error"] = str(e)[:200]

    return result


def main():
    parser = argparse.ArgumentParser(description="MAG-7 correlation check")
    parser.add_argument("--side", required=True, choices=["buy", "sell"])
    parser.add_argument("--ticker", default="", help="Underlying symbol for sector correlation breakdown")
    parser.add_argument("--output", default="mag7.json")
    args = parser.parse_args()

    result = check_mag7(args.side, ticker=args.ticker or None)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
