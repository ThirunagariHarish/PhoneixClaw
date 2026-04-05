"""Pre-market analysis — determines agent mode before market open."""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

log = logging.getLogger("pre_market_analyzer")

FUTURES_TICKERS = {"ES": "ES=F", "NQ": "NQ=F"}
VIX_TICKER = "^VIX"
VIX_9D_TICKER = "^VIX9D"
SECTOR_ETFS = ["XLK", "XLF", "XLE", "XLU", "XLY", "XLP"]

FOMC_2026 = [
    date(2026, 1, 28), date(2026, 1, 29),
    date(2026, 3, 17), date(2026, 3, 18),
    date(2026, 5, 5), date(2026, 5, 6),
    date(2026, 6, 16), date(2026, 6, 17),
    date(2026, 7, 28), date(2026, 7, 29),
    date(2026, 9, 15), date(2026, 9, 16),
    date(2026, 10, 27), date(2026, 10, 28),
    date(2026, 12, 15), date(2026, 12, 16),
]

CPI_RELEASE_DAYS_2026 = [
    date(2026, 1, 14), date(2026, 2, 12), date(2026, 3, 11),
    date(2026, 4, 10), date(2026, 5, 13), date(2026, 6, 10),
    date(2026, 7, 15), date(2026, 8, 12), date(2026, 9, 10),
    date(2026, 10, 14), date(2026, 11, 12), date(2026, 12, 10),
]


def _now_et() -> datetime:
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("America/New_York"))


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _fetch_quote(ticker: str) -> Optional[dict]:
    """Return last close, previous close, and percent change for *ticker*."""
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        hist = t.history(period="5d", interval="1d")
        if hist.empty or len(hist) < 2:
            hist = t.history(period="5d")
        if hist.empty or len(hist) < 2:
            return None

        prev_close = float(hist["Close"].iloc[-2])
        last_close = float(hist["Close"].iloc[-1])
        pct = ((last_close - prev_close) / prev_close) * 100 if prev_close else 0.0

        return {
            "ticker": ticker,
            "last": round(last_close, 2),
            "prev_close": round(prev_close, 2),
            "change_pct": round(pct, 2),
        }
    except Exception as exc:
        log.warning("fetch failed for %s: %s", ticker, exc)
        return None


def _fetch_vix() -> tuple[Optional[float], Optional[float]]:
    vix_data = _fetch_quote(VIX_TICKER)
    vix9d_data = _fetch_quote(VIX_9D_TICKER)
    vix = vix_data["last"] if vix_data else None
    vix9d = vix9d_data["last"] if vix9d_data else None
    return vix, vix9d


def fetch_futures() -> dict[str, Optional[dict]]:
    return {name: _fetch_quote(ticker) for name, ticker in FUTURES_TICKERS.items()}


def fetch_sectors() -> list[dict]:
    results = []
    for etf in SECTOR_ETFS:
        q = _fetch_quote(etf)
        if q:
            results.append(q)
    return results


# ---------------------------------------------------------------------------
# Calendar heuristic
# ---------------------------------------------------------------------------

def check_economic_calendar(today: date) -> dict:
    is_fomc = today in FOMC_2026
    is_cpi = today in CPI_RELEASE_DAYS_2026
    is_jobs = _is_jobs_friday(today)

    events = []
    if is_fomc:
        events.append("FOMC")
    if is_cpi:
        events.append("CPI")
    if is_jobs:
        events.append("NFP/Jobs")

    return {
        "is_event_day": bool(events),
        "events": events,
    }


def _is_jobs_friday(d: date) -> bool:
    """Non-farm payrolls typically release on the first Friday of the month."""
    if d.weekday() != 4:
        return False
    return d.day <= 7


# ---------------------------------------------------------------------------
# Mode determination
# ---------------------------------------------------------------------------

def determine_mode(
    vix: Optional[float],
    futures: dict[str, Optional[dict]],
    calendar: dict,
) -> tuple[str, list[str]]:
    """Return (mode, reasoning_list)."""
    reasons: list[str] = []

    if calendar.get("is_event_day"):
        reasons.append(f"major event day: {', '.join(calendar['events'])}")

    futures_down = False
    futures_up = False
    for name, data in futures.items():
        if data is None:
            continue
        pct = data["change_pct"]
        if pct < -0.5:
            futures_down = True
            reasons.append(f"{name} futures down {pct:.2f}%")
        elif pct > 0.3:
            futures_up = True
            reasons.append(f"{name} futures up +{pct:.2f}%")

    high_vix = False
    low_vix = False
    if vix is not None:
        if vix > 25:
            high_vix = True
            reasons.append(f"VIX elevated at {vix:.1f}")
        elif vix < 15:
            low_vix = True
            reasons.append(f"VIX low at {vix:.1f}")
        else:
            reasons.append(f"VIX neutral at {vix:.1f}")

    if high_vix or futures_down:
        return "conservative", reasons
    if low_vix and futures_up and not calendar.get("is_event_day"):
        return "aggressive", reasons

    reasons.append("defaulting to conservative (safe)")
    return "conservative", reasons


def classify_volatility(vix: Optional[float]) -> str:
    if vix is None:
        return "unknown"
    if vix < 15:
        return "low"
    if vix < 25:
        return "moderate"
    if vix < 35:
        return "high"
    return "extreme"


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze(config_path: str, output_path: str) -> dict:
    config_file = Path(config_path)
    config = _load_json(config_file)

    today = _now_et().date()
    log.info("running pre-market analysis for %s", today)

    vix, vix9d = _fetch_vix()
    log.info("VIX=%.2f  VIX9D=%s", vix or 0, vix9d)

    futures = fetch_futures()
    for name, data in futures.items():
        if data:
            log.info("%s futures: %.2f (%+.2f%%)", name, data["last"], data["change_pct"])

    sectors = fetch_sectors()
    sectors_sorted = sorted(sectors, key=lambda s: s["change_pct"], reverse=True)
    leaders = sectors_sorted[:2] if sectors_sorted else []
    laggards = sectors_sorted[-2:] if len(sectors_sorted) >= 2 else []

    for s in sectors:
        log.info("sector %s: %+.2f%%", s["ticker"], s["change_pct"])

    calendar = check_economic_calendar(today)
    if calendar["is_event_day"]:
        log.info("EVENT DAY: %s", ", ".join(calendar["events"]))

    mode, reasoning = determine_mode(vix, futures, calendar)
    vol_regime = classify_volatility(vix)

    overall_bias = "neutral"
    if futures:
        avg_chg = sum(
            d["change_pct"] for d in futures.values() if d is not None
        ) / max(1, sum(1 for d in futures.values() if d is not None))
        if avg_chg > 0.2:
            overall_bias = "bullish"
        elif avg_chg < -0.2:
            overall_bias = "bearish"

    context = {
        "date": str(today),
        "overall_bias": overall_bias,
        "volatility_regime": vol_regime,
        "vix": vix,
        "vix_9d": vix9d,
        "vix_term_structure": (
            "contango" if (vix and vix9d and vix9d < vix) else
            "backwardation" if (vix and vix9d and vix9d > vix) else
            "flat"
        ),
        "futures": {name: data for name, data in futures.items()},
        "sector_leaders": [s["ticker"] for s in leaders],
        "sector_laggards": [s["ticker"] for s in laggards],
        "sectors": sectors,
        "economic_calendar": calendar,
        "recommended_mode": mode,
        "reasoning": reasoning,
    }

    out = Path(output_path)
    _save_json(out, context)
    log.info("wrote market context to %s", out)

    current_mode = config.get("current_mode")
    if current_mode != mode:
        log.info("updating config mode: %s → %s", current_mode, mode)
        config["current_mode"] = mode
        _save_json(config_file, config)

    _report_to_phoenix(config, context)

    return context


def _report_to_phoenix(config: dict, context: dict) -> None:
    try:
        from tools.report_to_phoenix import report_heartbeat

        status = {
            "status": f"pre_market_{context['recommended_mode']}",
            "signals_processed": 0,
            "trades_today": 0,
        }
        asyncio.run(report_heartbeat(config, status))
    except Exception as exc:
        log.warning("failed to report to Phoenix: %s", exc)


def main():
    parser = argparse.ArgumentParser(description="Pre-market analysis — set agent mode before open")
    parser.add_argument("--config", required=True, help="Path to config.json")
    parser.add_argument("--output", default="market_context.json", help="Output market context file")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    ctx = analyze(args.config, args.output)

    print(json.dumps({
        "date": ctx["date"],
        "mode": ctx["recommended_mode"],
        "bias": ctx["overall_bias"],
        "vix": ctx["vix"],
        "volatility": ctx["volatility_regime"],
    }, indent=2))


if __name__ == "__main__":
    main()
