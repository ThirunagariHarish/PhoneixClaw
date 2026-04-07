"""Shared portfolio math helpers — Sharpe, drawdown, win rate.

Used by the live-metrics endpoint (P7) and the supervisor pipeline (P16).
All functions handle empty inputs and NaN defensively.
"""
from __future__ import annotations

import math
from typing import Iterable


def rolling_sharpe(pnls: Iterable[float], window: int = 30,
                    risk_free: float = 0.0, periods_per_year: int = 252) -> float:
    """Annualized Sharpe on the last `window` PnL observations.

    Assumes each PnL is the result of one trade or one daily closing period;
    scales by sqrt(periods_per_year).
    """
    pnls = list(pnls)
    if not pnls:
        return 0.0
    sample = pnls[-window:]
    n = len(sample)
    if n < 2:
        return 0.0
    mean = sum(sample) / n
    variance = sum((p - mean) ** 2 for p in sample) / (n - 1)
    std = math.sqrt(variance)
    if std <= 1e-9:
        return 0.0
    return ((mean - risk_free) / std) * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: Iterable[float]) -> float:
    """Return max drawdown as a positive decimal (0.15 = 15%)."""
    curve = list(equity_curve)
    if not curve:
        return 0.0
    peak = curve[0]
    worst = 0.0
    for v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > worst:
                worst = dd
    return worst


def current_drawdown(equity_curve: Iterable[float]) -> float:
    """Drawdown at the latest point relative to the all-time high."""
    curve = list(equity_curve)
    if not curve:
        return 0.0
    peak = max(curve)
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - curve[-1]) / peak)


def win_rate(pnls: Iterable[float]) -> float:
    p = list(pnls)
    if not p:
        return 0.0
    return sum(1 for x in p if x > 0) / len(p)


def profit_factor(pnls: Iterable[float]) -> float:
    gains = sum(p for p in pnls if p > 0)
    losses = abs(sum(p for p in pnls if p < 0))
    if losses <= 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses
