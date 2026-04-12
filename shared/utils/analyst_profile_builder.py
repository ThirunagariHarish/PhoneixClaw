"""Build analyst behavior profiles from historical trade data.

Queries the agent_trades table, groups by analyst, and computes behavioral
statistics that power the analyst exit prediction engine and enrichment
pipeline features.

Can run standalone (CLI) or be imported by the supervisor auto-research loop.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _extract_analyst_name(trade: dict) -> str | None:
    """Extract analyst name from a trade's signal_raw or decision_trail."""
    if trade.get("decision_trail"):
        trail = trade["decision_trail"]
        if isinstance(trail, str):
            try:
                trail = json.loads(trail)
            except (json.JSONDecodeError, TypeError):
                trail = {}
        for key in ("analyst", "author", "analyst_name", "channel_author"):
            if trail.get(key):
                return str(trail[key]).strip()
        parsed = trail.get("parsed_signal", {})
        if isinstance(parsed, dict) and parsed.get("author"):
            return str(parsed["author"]).strip()

    raw = trade.get("signal_raw", "")
    if raw:
        try:
            sig = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(sig, dict):
                for key in ("author", "analyst", "username"):
                    if sig.get(key):
                        return str(sig[key]).strip()
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def build_profile_from_trades(trades: list[dict]) -> dict[str, Any] | None:
    """Compute a behavioral profile from a list of trade dicts.

    Expects each dict to have keys from AgentTrade:
    entry_time, exit_time, pnl_pct, entry_price, exit_price,
    model_confidence, signal_raw, decision_trail, status
    """
    closed = [t for t in trades if t.get("exit_time") and t.get("pnl_pct") is not None]
    if len(closed) < 3:
        return None

    pnls = [float(t["pnl_pct"]) for t in closed]
    wins = [1 if p > 0 else 0 for p in pnls]

    hold_hours = []
    for t in closed:
        entry = t["entry_time"]
        exit_ = t["exit_time"]
        if isinstance(entry, str):
            entry = datetime.fromisoformat(entry)
        if isinstance(exit_, str):
            exit_ = datetime.fromisoformat(exit_)
        if entry and exit_:
            hold_hours.append((exit_ - entry).total_seconds() / 3600)

    entry_hours = []
    exit_hours = []
    exit_dows: dict[int, int] = {}
    for t in closed:
        et = t["entry_time"]
        xt = t["exit_time"]
        if isinstance(et, str):
            et = datetime.fromisoformat(et)
        if isinstance(xt, str):
            xt = datetime.fromisoformat(xt)
        if et:
            entry_hours.append(et.hour + et.minute / 60)
        if xt:
            exit_hours.append(xt.hour + xt.minute / 60)
            dow = xt.weekday()
            exit_dows[dow] = exit_dows.get(dow, 0) + 1

    confidences = [
        float(t["model_confidence"])
        for t in trades
        if t.get("model_confidence") is not None
    ]

    # Drawdown tolerance: median of worst P&L before exit for losing trades
    losing_pnls = [p for p in pnls if p < 0]
    drawdown_tolerance = float(np.median(losing_pnls)) if losing_pnls else -5.0

    # Rolling win rates
    win_rate_10 = float(np.mean(wins[-10:])) if len(wins) >= 10 else float(np.mean(wins))
    win_rate_20 = float(np.mean(wins[-20:])) if len(wins) >= 20 else float(np.mean(wins))

    profile = {
        "total_trades": len(trades),
        "win_rate_10": round(win_rate_10, 4),
        "win_rate_20": round(win_rate_20, 4),
        "avg_hold_hours": round(float(np.mean(hold_hours)), 2) if hold_hours else None,
        "median_exit_pnl": round(float(np.median(pnls)), 4),
        "exit_pnl_p25": round(float(np.percentile(pnls, 25)), 4),
        "exit_pnl_p75": round(float(np.percentile(pnls, 75)), 4),
        "avg_entry_hour": round(float(np.mean(entry_hours)), 2) if entry_hours else None,
        "avg_exit_hour": round(float(np.mean(exit_hours)), 2) if exit_hours else None,
        "preferred_exit_dow": exit_dows,
        "drawdown_tolerance": round(drawdown_tolerance, 4),
        "conviction_score": round(float(np.mean(confidences)), 4) if confidences else None,
        "post_earnings_sell_rate": None,  # requires earnings data, computed separately
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "profile_data": {
            "pnl_std": round(float(np.std(pnls)), 4),
            "avg_pnl": round(float(np.mean(pnls)), 4),
            "hold_hours_std": round(float(np.std(hold_hours)), 2) if len(hold_hours) > 1 else 0,
            "hold_hours_median": round(float(np.median(hold_hours)), 2) if hold_hours else None,
            "peak_exit_hours": _peak_hours(exit_hours),
            "peak_exit_days": _peak_days(exit_dows),
            "win_streak_max": _max_streak(wins),
            "lose_streak_max": _max_streak([1 - w for w in wins]),
        },
    }
    return profile


def _peak_hours(hours: list[float], top_n: int = 3) -> list[int]:
    """Return the top N hours by frequency."""
    if not hours:
        return []
    counts: dict[int, int] = {}
    for h in hours:
        bucket = int(h)
        counts[bucket] = counts.get(bucket, 0) + 1
    return sorted(counts, key=counts.get, reverse=True)[:top_n]  # type: ignore[arg-type]


def _peak_days(dow_counts: dict[int, int], top_n: int = 2) -> list[int]:
    """Return the top N days of week by exit frequency."""
    if not dow_counts:
        return []
    return sorted(dow_counts, key=dow_counts.get, reverse=True)[:top_n]  # type: ignore[arg-type]


def _max_streak(binary: list[int]) -> int:
    """Max consecutive 1s in a binary list."""
    best = current = 0
    for v in binary:
        if v:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


async def refresh_all_profiles(db_session) -> dict[str, int]:
    """Query all trades and rebuild every analyst profile.

    Returns summary: {"profiles_created": N, "profiles_updated": M}
    """
    from sqlalchemy import select

    from shared.db.models.agent_trade import AgentTrade
    from shared.db.models.analyst_profile import AnalystProfile

    result = await db_session.execute(select(AgentTrade))
    all_trades = result.scalars().all()

    by_analyst: dict[str, list[dict]] = {}
    for t in all_trades:
        trade_dict = {
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "pnl_pct": t.pnl_pct,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "model_confidence": t.model_confidence,
            "signal_raw": t.signal_raw,
            "decision_trail": t.decision_trail,
            "status": t.status,
            "ticker": t.ticker,
        }
        name = _extract_analyst_name(trade_dict)
        if name:
            by_analyst.setdefault(name, []).append(trade_dict)

    created = updated = 0
    for analyst_name, trades in by_analyst.items():
        profile_data = build_profile_from_trades(trades)
        if not profile_data:
            continue

        existing = (await db_session.execute(
            select(AnalystProfile).where(AnalystProfile.analyst_name == analyst_name)
        )).scalar_one_or_none()

        row = dict(profile_data)
        row.pop("updated_at", None)
        nested = row.pop("profile_data", None)

        if existing:
            for key, val in row.items():
                if val is not None and hasattr(existing, key):
                    setattr(existing, key, val)
            if nested is not None:
                existing.profile_data = nested
            existing.updated_at = datetime.now(timezone.utc)
            updated += 1
        else:
            db_session.add(AnalystProfile(
                analyst_name=analyst_name,
                profile_data=nested,
                updated_at=datetime.now(timezone.utc),
                **{k: v for k, v in row.items() if k != "analyst_name"},
            ))
            created += 1

    await db_session.commit()
    logger.info("Analyst profiles refreshed: %d created, %d updated", created, updated)
    return {"profiles_created": created, "profiles_updated": updated}


def get_analyst_features_for_trade(profile: dict, trade: dict, *, as_of: datetime | None = None) -> dict[str, float]:
    """Generate enrichment features from an analyst profile for a single trade row.

    Used by enrich.py and enrich_single.py to add ~15 analyst behavior features.

    Args:
        as_of: Optional point-in-time for backtest mode. When provided, used instead
               of datetime.now() for computing hold-time-dependent features, avoiding
               temporal data leakage.
    """
    features: dict[str, float] = {}
    if not profile:
        return features

    features["analyst_rolling_win_rate_10"] = profile.get("win_rate_10", np.nan)
    features["analyst_rolling_win_rate_20"] = profile.get("win_rate_20", np.nan)
    features["analyst_avg_hold_hours"] = profile.get("avg_hold_hours", np.nan)
    features["analyst_median_exit_pnl"] = profile.get("median_exit_pnl", np.nan)
    features["analyst_exit_pnl_p25"] = profile.get("exit_pnl_p25", np.nan)
    features["analyst_exit_pnl_p75"] = profile.get("exit_pnl_p75", np.nan)
    features["analyst_typical_entry_hour"] = profile.get("avg_entry_hour", np.nan)
    features["analyst_typical_exit_hour"] = profile.get("avg_exit_hour", np.nan)

    exit_dow = profile.get("preferred_exit_dow", {})
    if isinstance(exit_dow, str):
        try:
            exit_dow = json.loads(exit_dow)
        except (json.JSONDecodeError, TypeError):
            exit_dow = {}
    features["analyst_exit_dow_monday"] = float(exit_dow.get("0", exit_dow.get(0, 0)))
    features["analyst_exit_dow_friday"] = float(exit_dow.get("4", exit_dow.get(4, 0)))

    features["analyst_drawdown_tolerance"] = profile.get("drawdown_tolerance", np.nan)
    features["analyst_conviction_score"] = profile.get("conviction_score", np.nan)
    features["analyst_post_earnings_sell_rate"] = profile.get("post_earnings_sell_rate", np.nan)

    # Derived: hold time ratio (requires current trade's hold duration)
    avg_hold = profile.get("avg_hold_hours")
    entry_time = trade.get("entry_time")
    if avg_hold and entry_time:
        if isinstance(entry_time, str):
            entry_time = datetime.fromisoformat(entry_time)
        ref_time = as_of if as_of is not None else datetime.now(timezone.utc)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        current_hold = (ref_time - entry_time).total_seconds() / 3600
        features["analyst_hold_time_ratio"] = round(current_hold / avg_hold, 4) if avg_hold > 0 else np.nan
    else:
        features["analyst_hold_time_ratio"] = np.nan

    # Derived: P&L vs typical exit
    median_pnl = profile.get("median_exit_pnl")
    current_pnl = trade.get("pnl_pct")
    if median_pnl and current_pnl is not None and median_pnl != 0:
        features["analyst_pnl_vs_typical"] = round(float(current_pnl) / abs(median_pnl), 4)
    else:
        features["analyst_pnl_vs_typical"] = np.nan

    return features
