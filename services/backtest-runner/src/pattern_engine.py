"""
Pattern recognition engine — analyzes enriched backtest trades to discover
profitable patterns and generate intelligence rules with weights.

Outputs a set of PatternRules stored as JSONB on AgentBacktest.metrics.
"""

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional

from shared.db.models.backtest_trade import BacktestTrade

logger = logging.getLogger(__name__)


@dataclass
class PatternRule:
    name: str
    condition: str
    win_rate: float
    sample_size: int
    weight: float  # -1.0 to 1.0, positive = take trade, negative = avoid


def analyze_patterns(trades: list[BacktestTrade]) -> dict:
    """
    Analyze enriched trades and discover profitable patterns.
    Returns a dict suitable for storing in AgentBacktest.metrics.
    """
    if not trades:
        return {"rules": [], "overall_channel_metrics": {}}

    rules: list[dict] = []
    total = len(trades)
    profitable = [t for t in trades if t.is_profitable]
    losing = [t for t in trades if not t.is_profitable]

    overall_win_rate = len(profitable) / total if total > 0 else 0
    avg_win = sum(t.pnl_pct for t in profitable) / len(profitable) if profitable else 0
    avg_loss = sum(t.pnl_pct for t in losing) / len(losing) if losing else 0

    # ── Time-based patterns ──────────────────────────────────────────────
    hour_buckets = _bucket_analysis(trades, lambda t: t.hour_of_day)
    for hour, stats in hour_buckets.items():
        if hour is None or stats["count"] < 3:
            continue
        wr = stats["win_rate"]
        w = _compute_weight(wr, overall_win_rate, stats["count"])
        label = f"{hour}:00-{hour}:59"
        if abs(w) > 0.15:
            rules.append({
                "name": f"hour_{hour}",
                "condition": f"hour_of_day == {hour}",
                "description": f"Trades at {label}",
                "win_rate": round(wr, 3),
                "sample_size": stats["count"],
                "weight": round(w, 3),
            })

    # Best/worst hour windows
    morning_trades = [t for t in trades if t.hour_of_day is not None and 9 <= t.hour_of_day <= 11]
    afternoon_trades = [t for t in trades if t.hour_of_day is not None and 12 <= t.hour_of_day <= 15]
    if len(morning_trades) >= 5:
        wr = sum(1 for t in morning_trades if t.is_profitable) / len(morning_trades)
        rules.append({
            "name": "morning_window",
            "condition": "hour_of_day between 9 and 11",
            "description": "Trades during morning session (9-11 AM)",
            "win_rate": round(wr, 3),
            "sample_size": len(morning_trades),
            "weight": round(_compute_weight(wr, overall_win_rate, len(morning_trades)), 3),
        })
    if len(afternoon_trades) >= 5:
        wr = sum(1 for t in afternoon_trades if t.is_profitable) / len(afternoon_trades)
        rules.append({
            "name": "afternoon_window",
            "condition": "hour_of_day between 12 and 15",
            "description": "Trades during afternoon session (12-3 PM)",
            "win_rate": round(wr, 3),
            "sample_size": len(afternoon_trades),
            "weight": round(_compute_weight(wr, overall_win_rate, len(afternoon_trades)), 3),
        })

    # Day of week patterns
    dow_buckets = _bucket_analysis(trades, lambda t: t.day_of_week)
    dow_names = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday"}
    for dow, stats in dow_buckets.items():
        if dow is None or stats["count"] < 3:
            continue
        wr = stats["win_rate"]
        w = _compute_weight(wr, overall_win_rate, stats["count"])
        if abs(w) > 0.15:
            rules.append({
                "name": f"day_{dow_names.get(dow, str(dow)).lower()}",
                "condition": f"day_of_week == {dow}",
                "description": f"Trades on {dow_names.get(dow, str(dow))}",
                "win_rate": round(wr, 3),
                "sample_size": stats["count"],
                "weight": round(w, 3),
            })

    # ── RSI patterns ─────────────────────────────────────────────────────
    rsi_trades = [t for t in trades if t.entry_rsi is not None]
    if len(rsi_trades) >= 5:
        oversold = [t for t in rsi_trades if t.entry_rsi < 30]
        overbought = [t for t in rsi_trades if t.entry_rsi > 70]
        neutral = [t for t in rsi_trades if 30 <= t.entry_rsi <= 70]

        for label, subset, condition in [
            ("rsi_oversold", oversold, "entry_rsi < 30"),
            ("rsi_overbought", overbought, "entry_rsi > 70"),
            ("rsi_neutral", neutral, "30 <= entry_rsi <= 70"),
        ]:
            if len(subset) >= 3:
                wr = sum(1 for t in subset if t.is_profitable) / len(subset)
                rules.append({
                    "name": label,
                    "condition": condition,
                    "description": f"Trades when RSI is {label.split('_')[1]}",
                    "win_rate": round(wr, 3),
                    "sample_size": len(subset),
                    "weight": round(_compute_weight(wr, overall_win_rate, len(subset)), 3),
                })

    # High RSI avoidance (>80)
    high_rsi = [t for t in rsi_trades if t.entry_rsi and t.entry_rsi > 80]
    if len(high_rsi) >= 3:
        wr = sum(1 for t in high_rsi if t.is_profitable) / len(high_rsi)
        rules.append({
            "name": "high_rsi_avoid",
            "condition": "entry_rsi > 80",
            "description": "Trades when RSI is extremely overbought (>80)",
            "win_rate": round(wr, 3),
            "sample_size": len(high_rsi),
            "weight": round(_compute_weight(wr, overall_win_rate, len(high_rsi)), 3),
        })

    # ── Author trust patterns ────────────────────────────────────────────
    author_counter: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
    for t in trades:
        # Author info would be in the signal message — here we use pattern_tags or a join
        # For now, we'll skip author patterns unless we have the data
        pass

    # ── Ticker patterns ──────────────────────────────────────────────────
    ticker_buckets = _bucket_analysis(trades, lambda t: t.ticker)
    for ticker, stats in ticker_buckets.items():
        if stats["count"] < 3:
            continue
        wr = stats["win_rate"]
        w = _compute_weight(wr, overall_win_rate, stats["count"])
        if abs(w) > 0.2:
            rules.append({
                "name": f"ticker_{ticker.lower()}",
                "condition": f"ticker == '{ticker}'",
                "description": f"Trades on {ticker}",
                "win_rate": round(wr, 3),
                "sample_size": stats["count"],
                "weight": round(w, 3),
            })

    # ── VIX regime patterns ──────────────────────────────────────────────
    vix_trades = [t for t in trades if t.market_vix is not None]
    if len(vix_trades) >= 5:
        low_vix = [t for t in vix_trades if t.market_vix < 20]
        high_vix = [t for t in vix_trades if t.market_vix >= 25]

        for label, subset, condition in [
            ("vix_low", low_vix, "market_vix < 20"),
            ("vix_high", high_vix, "market_vix >= 25"),
        ]:
            if len(subset) >= 3:
                wr = sum(1 for t in subset if t.is_profitable) / len(subset)
                rules.append({
                    "name": label,
                    "condition": condition,
                    "description": f"Trades when VIX is {'low (<20)' if 'low' in label else 'high (>=25)'}",
                    "win_rate": round(wr, 3),
                    "sample_size": len(subset),
                    "weight": round(_compute_weight(wr, overall_win_rate, len(subset)), 3),
                })

    # ── Pre-market pattern ───────────────────────────────────────────────
    pre_market = [t for t in trades if t.is_pre_market]
    if len(pre_market) >= 3:
        wr = sum(1 for t in pre_market if t.is_profitable) / len(pre_market)
        rules.append({
            "name": "pre_market",
            "condition": "is_pre_market == true",
            "description": "Trades taken during pre-market hours",
            "win_rate": round(wr, 3),
            "sample_size": len(pre_market),
            "weight": round(_compute_weight(wr, overall_win_rate, len(pre_market)), 3),
        })

    # ── Volume ratio patterns ────────────────────────────────────────────
    vol_trades = [t for t in trades if t.entry_volume_ratio is not None]
    if len(vol_trades) >= 5:
        high_vol = [t for t in vol_trades if t.entry_volume_ratio > 1.5]
        low_vol = [t for t in vol_trades if t.entry_volume_ratio < 0.7]

        for label, subset, condition in [
            ("high_volume", high_vol, "entry_volume_ratio > 1.5"),
            ("low_volume", low_vol, "entry_volume_ratio < 0.7"),
        ]:
            if len(subset) >= 3:
                wr = sum(1 for t in subset if t.is_profitable) / len(subset)
                rules.append({
                    "name": label,
                    "condition": condition,
                    "description": f"Trades with {'high' if 'high' in label else 'low'} relative volume",
                    "win_rate": round(wr, 3),
                    "sample_size": len(subset),
                    "weight": round(_compute_weight(wr, overall_win_rate, len(subset)), 3),
                })

    # Sort rules by absolute weight (most impactful first)
    rules.sort(key=lambda r: abs(r["weight"]), reverse=True)

    # Find best ticker, best hour, best author
    ticker_wr = {t: s["win_rate"] for t, s in ticker_buckets.items() if s["count"] >= 3}
    best_ticker = max(ticker_wr, key=ticker_wr.get) if ticker_wr else None
    hour_wr = {h: s["win_rate"] for h, s in hour_buckets.items() if h is not None and s["count"] >= 3}
    best_hour = max(hour_wr, key=hour_wr.get) if hour_wr else None

    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    return {
        "rules": rules,
        "overall_channel_metrics": {
            "total_messages_analyzed": 0,  # Will be set by pipeline
            "total_signals_found": 0,
            "total_trades_identified": total,
            "profitable_trades": len(profitable),
            "losing_trades": len(losing),
            "overall_win_rate": round(overall_win_rate, 4),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
            "best_ticker": best_ticker,
            "best_hour": best_hour,
            "rules_count": len(rules),
        },
    }


def _bucket_analysis(trades: list[BacktestTrade], key_fn) -> dict:
    """Group trades by a key function and compute win rate per bucket."""
    buckets: dict = defaultdict(lambda: {"wins": 0, "total": 0, "pnl_sum": 0.0})
    for t in trades:
        k = key_fn(t)
        buckets[k]["total"] += 1
        buckets[k]["pnl_sum"] += t.pnl_pct
        if t.is_profitable:
            buckets[k]["wins"] += 1

    result = {}
    for k, v in buckets.items():
        result[k] = {
            "count": v["total"],
            "wins": v["wins"],
            "win_rate": v["wins"] / v["total"] if v["total"] > 0 else 0,
            "avg_pnl": v["pnl_sum"] / v["total"] if v["total"] > 0 else 0,
        }
    return result


def _compute_weight(bucket_wr: float, overall_wr: float, sample_size: int) -> float:
    """
    Compute a rule weight based on how much the bucket win rate deviates
    from the overall win rate, adjusted by sample size confidence.
    """
    deviation = bucket_wr - overall_wr
    # Confidence factor: ramps from 0 to 1 as sample_size goes from 0 to 20
    confidence = min(1.0, sample_size / 20.0)
    return deviation * confidence * 2  # Scale to roughly -1 to 1
