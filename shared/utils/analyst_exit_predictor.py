"""Analyst exit prediction engine.

Uses the AnalystProfile (built by analyst_profile_builder) to compute a
0-100 probability that the analyst is about to sell a position, along with
explanatory reasons. This probability is fed into the position monitor's
LLM prompt and urgency scoring.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def predict_analyst_exit(
    profile: dict[str, Any],
    position: dict[str, Any],
    current_price: float | None = None,
) -> dict[str, Any]:
    """Compute 0-100 probability that the analyst is about to sell.

    Args:
        profile: AnalystProfile fields (from DB or dict).
        position: Current position data (entry_price, entry_time, side, etc.).
        current_price: Live price (if available).

    Returns:
        {"probability": int, "reasons": list[str], "signals": dict}
    """
    if not profile or not profile.get("avg_hold_hours"):
        return {"probability": 0, "reasons": ["no_analyst_profile"], "signals": {}}

    probability = 0
    reasons: list[str] = []
    signals: dict[str, Any] = {}

    entry_price = float(position.get("entry_price", 0))
    side = position.get("side", "buy")

    # Current P&L
    pnl_pct = 0.0
    if current_price and entry_price > 0:
        if side == "buy":
            pnl_pct = (current_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - current_price) / entry_price * 100
    signals["current_pnl_pct"] = round(pnl_pct, 2)

    # ----- Hold time ratio -----
    avg_hold = profile.get("avg_hold_hours", 0)
    entry_time = position.get("entry_time") or position.get("opened_at")
    if avg_hold and entry_time:
        if isinstance(entry_time, str):
            try:
                entry_time = datetime.fromisoformat(entry_time)
            except ValueError:
                entry_time = None
        if entry_time:
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)
            current_hold_hours = (datetime.now(timezone.utc) - entry_time).total_seconds() / 3600
            hold_ratio = current_hold_hours / avg_hold if avg_hold > 0 else 0
            signals["hold_ratio"] = round(hold_ratio, 2)
            signals["current_hold_hours"] = round(current_hold_hours, 1)

            if hold_ratio > 1.5:
                probability += 30
                reasons.append(f"Significantly overstaying: held {hold_ratio:.1f}x analyst avg ({avg_hold:.0f}h)")
            elif hold_ratio > 1.2:
                probability += 25
                reasons.append(f"Overstaying: held {hold_ratio:.1f}x analyst avg ({avg_hold:.0f}h)")
            elif hold_ratio > 0.8:
                probability += 10
                reasons.append(f"Approaching analyst avg hold time ({hold_ratio:.1f}x)")

    # ----- P&L vs typical exit range -----
    exit_p75 = profile.get("exit_pnl_p75")
    exit_p25 = profile.get("exit_pnl_p25")
    median_exit = profile.get("median_exit_pnl")

    if exit_p75 is not None and pnl_pct >= exit_p75:
        probability += 20
        reasons.append(f"P&L {pnl_pct:.1f}% above analyst's 75th percentile exit ({exit_p75:.1f}%)")
    elif median_exit is not None and pnl_pct >= median_exit:
        probability += 10
        reasons.append(f"P&L {pnl_pct:.1f}% above analyst's median exit ({median_exit:.1f}%)")

    if exit_p25 is not None and pnl_pct < 0 and pnl_pct <= exit_p25:
        probability += 15
        reasons.append(f"P&L {pnl_pct:.1f}% below analyst's 25th percentile exit ({exit_p25:.1f}%)")

    # ----- Time of day pattern -----
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    # Convert UTC to ET (approximate: UTC-4 for EDT, UTC-5 for EST)
    et_hour = (current_hour - 4) % 24

    avg_exit_hour = profile.get("avg_exit_hour")
    profile_data = profile.get("profile_data", {}) or {}
    peak_exit_hours = profile_data.get("peak_exit_hours", [])

    if peak_exit_hours and et_hour in peak_exit_hours:
        probability += 15
        reasons.append(f"Analyst typically exits around {et_hour}:00 ET")
    elif avg_exit_hour is not None and abs(et_hour - avg_exit_hour) <= 1:
        probability += 10
        reasons.append(f"Near analyst's average exit hour ({avg_exit_hour:.0f}:00 ET)")

    signals["current_hour_et"] = et_hour

    # ----- Day of week pattern -----
    today_dow = now.weekday()  # 0=Mon, 4=Fri
    exit_dow = profile.get("preferred_exit_dow", {}) or {}
    if isinstance(exit_dow, str):
        import json
        try:
            exit_dow = json.loads(exit_dow)
        except Exception:
            exit_dow = {}

    peak_exit_days = profile_data.get("peak_exit_days", [])
    if today_dow in peak_exit_days or str(today_dow) in exit_dow:
        dow_count = exit_dow.get(str(today_dow), exit_dow.get(today_dow, 0))
        total_exits = sum(exit_dow.values()) if exit_dow else 1
        if total_exits > 0 and dow_count / total_exits > 0.25:
            probability += 10
            day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            reasons.append(f"Analyst frequently exits on {day_names[today_dow]}s "
                           f"({dow_count}/{total_exits} = {dow_count/total_exits:.0%})")

    # ----- Friday afternoon risk (options) -----
    if today_dow == 4 and et_hour >= 14:
        probability += 10
        reasons.append("Friday afternoon — elevated close risk for weekly options")

    # ----- Upcoming earnings -----
    post_earn_sell = profile.get("post_earnings_sell_rate")
    if post_earn_sell is not None and post_earn_sell > 0.6:
        try:
            import yfinance as yf
            ticker = position.get("ticker", "")
            if ticker:
                tk = yf.Ticker(ticker)
                cal = tk.calendar
                if cal is not None:
                    earnings_dates = []
                    if isinstance(cal, dict):
                        earnings_dates = cal.get("Earnings Date", [])
                    elif hasattr(cal, "columns") and "Earnings Date" in cal.columns:
                        earnings_dates = cal["Earnings Date"].tolist()
                    for ed in earnings_dates:
                        if hasattr(ed, "date"):
                            ed = ed.date()
                        if isinstance(ed, date) and 0 <= (ed - date.today()).days <= 2:
                            probability += 20
                            reasons.append(
                                f"Earnings within 2 days and analyst sells before earnings "
                                f"{post_earn_sell:.0%} of the time"
                            )
                            break
        except Exception:
            pass

    # ----- Drawdown tolerance -----
    drawdown_tol = profile.get("drawdown_tolerance")
    if drawdown_tol is not None and pnl_pct < 0:
        tolerance_ratio = abs(pnl_pct) / abs(drawdown_tol) if drawdown_tol != 0 else 0
        signals["drawdown_ratio"] = round(tolerance_ratio, 2)
        if tolerance_ratio > 0.9:
            probability += 20
            reasons.append(f"At analyst's drawdown limit ({pnl_pct:.1f}% vs tolerance {drawdown_tol:.1f}%)")
        elif tolerance_ratio > 0.7:
            probability += 15
            reasons.append(f"Approaching analyst's drawdown tolerance ({tolerance_ratio:.0%} used)")

    # ----- Win rate declining -----
    wr10 = profile.get("win_rate_10")
    wr20 = profile.get("win_rate_20")
    if wr10 is not None and wr20 is not None and wr10 < wr20 - 0.1:
        probability += 5
        reasons.append(f"Analyst win rate declining: last 10={wr10:.0%} vs last 20={wr20:.0%}")

    probability = min(probability, 100)
    signals["probability"] = probability

    return {
        "probability": probability,
        "reasons": reasons,
        "signals": signals,
    }
