"""Phase 2: Enrich trade_signals with +1h/+4h/EOD price outcomes.

Pulls today's trade_signals rows via the Phoenix API, fetches each ticker's
price at the signal time + 1h/4h/EOD, and writes the enriched rows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _price_at(ticker: str, at: datetime) -> float | None:
    try:
        import yfinance as yf
        data = yf.Ticker(ticker).history(
            start=(at - timedelta(hours=2)).strftime("%Y-%m-%d"),
            end=(at + timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="5m",
        )
        if data.empty:
            return None
        data.index = data.index.tz_convert("UTC") if data.index.tz else data.index.tz_localize("UTC")
        idx = data.index[data.index >= at]
        if len(idx) == 0:
            return float(data["Close"].iloc[-1])
        return float(data.loc[idx[0], "Close"])
    except Exception:
        return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="signals_enriched.json")
    args = p.parse_args()

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    import httpx
    base = os.environ.get("PHOENIX_API_URL", "http://localhost:8011")
    key = os.environ.get("PHOENIX_API_KEY", "")
    headers = {"X-Agent-Key": key} if key else {}

    try:
        r = httpx.get(
            f"{base}/api/v2/trade-signals?since={today_start.isoformat()}&limit=500",
            headers=headers, timeout=15,
        )
        signals = r.json() if r.status_code == 200 else []
        if isinstance(signals, dict):
            signals = signals.get("signals", [])
        if not isinstance(signals, list):
            signals = []
    except Exception as exc:
        print(f"[enrich] trade-signals fetch failed: {exc}", file=sys.stderr)
        signals = []

    enriched: list[dict] = []
    for sig in signals:
        ticker = (sig.get("ticker") or sig.get("symbol") or "").upper()
        signal_time_raw = sig.get("created_at") or sig.get("signal_at")
        entry_price = sig.get("entry_price") or sig.get("signal_price")
        if not ticker or not signal_time_raw or not entry_price:
            continue
        try:
            signal_time = datetime.fromisoformat(signal_time_raw.replace("Z", "+00:00"))
        except Exception:
            continue

        price_1h = _price_at(ticker, signal_time + timedelta(hours=1))
        price_4h = _price_at(ticker, signal_time + timedelta(hours=4))
        price_eod = _price_at(ticker, signal_time.replace(hour=20, minute=0))

        entry = float(entry_price)
        direction = (sig.get("direction") or "buy").lower()
        side_sign = 1 if direction == "buy" else -1

        def _pct(p):
            if p is None or entry == 0:
                return None
            return round(((p - entry) / entry * 100) * side_sign, 3)

        enriched.append({
            "id": sig.get("id"),
            "agent_id": sig.get("agent_id"),
            "ticker": ticker,
            "direction": direction,
            "decision": sig.get("decision"),
            "entry_price": entry,
            "signal_at": signal_time.isoformat(),
            "price_1h": price_1h,
            "price_4h": price_4h,
            "price_eod": price_eod,
            "pct_1h": _pct(price_1h),
            "pct_4h": _pct(price_4h),
            "pct_eod": _pct(price_eod),
        })

    result = {"enriched_count": len(enriched), "signals": enriched}
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(f"[enrich] enriched {len(enriched)} signals")


if __name__ == "__main__":
    main()
