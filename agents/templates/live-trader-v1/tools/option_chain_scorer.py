"""T6: Deterministic option-chain scorer.

Scores every contract within ±5 strikes of the analyst's strike on:
    - Bid-ask spread in % of mid (penalty)
    - Open interest + volume (liquidity bonus)
    - |delta - 0.45| (directional sweet spot)
    - IV - HV30 excess (penalty on overpriced premium)
    - Theta / premium ratio (penalty on high decay)
    - DTE alignment with predicted hold (T4)

Mode: SANITY-CHECK — accepts analyst strikes unless they score below the
25th percentile of scored contracts (per the user's T6 answer during planning).

Usage as a library:
    from option_chain_scorer import score_chain, sanity_check_analyst_strike
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

TARGET_DELTA = 0.45
STRIKE_RADIUS = 5
ACCEPT_PERCENTILE = 0.25  # reject analyst strike if its score is below this


@dataclass
class ContractScore:
    strike: float
    expiry: str
    option_type: str
    score: float
    components: dict[str, float]


def _score_contract(c: dict, hv30: float | None, predicted_hold_days: float | None) -> float:
    """Higher is better. Bounded roughly [-1.0, 1.0]."""
    score = 0.0
    mid = 0.5 * (float(c.get("bid", 0) or 0) + float(c.get("ask", 0) or 0))
    if mid <= 0:
        return -1.0

    spread_pct = abs(float(c.get("ask", 0) or 0) - float(c.get("bid", 0) or 0)) / mid
    score -= min(0.5, spread_pct * 2.5)  # wide spread = big penalty

    oi = float(c.get("open_interest", 0) or 0)
    vol = float(c.get("volume", 0) or 0)
    score += 0.25 * min(1.0, (oi + vol) / 2000.0)

    delta = abs(float(c.get("delta", 0) or 0))
    score -= min(0.4, abs(delta - TARGET_DELTA) * 1.2)

    iv = float(c.get("implied_volatility", 0) or 0)
    if hv30 and iv:
        iv_excess = iv - hv30
        if iv_excess > 0:
            score -= min(0.3, iv_excess * 1.5)

    theta = abs(float(c.get("theta", 0) or 0))
    if mid > 0:
        theta_ratio = theta / mid
        score -= min(0.3, theta_ratio * 5.0)

    dte = float(c.get("days_to_expiry", 0) or 0)
    if predicted_hold_days and predicted_hold_days > 0:
        # Ideal DTE ≈ 3x predicted hold (enough buffer for theta)
        ideal = predicted_hold_days * 3
        misalignment = abs(dte - ideal) / max(ideal, 1.0)
        score -= min(0.25, misalignment * 0.3)

    return float(score)


def score_chain(chain: list[dict], *, hv30: float | None = None,
                predicted_hold_minutes: float | None = None) -> list[ContractScore]:
    """Score every contract in `chain`. Returns list sorted by score desc."""
    hold_days = (predicted_hold_minutes / (60 * 6.5)) if predicted_hold_minutes else None
    scored = []
    for c in chain:
        s = _score_contract(c, hv30, hold_days)
        scored.append(ContractScore(
            strike=float(c.get("strike", 0) or 0),
            expiry=str(c.get("expiry", "")),
            option_type=str(c.get("option_type", "call")),
            score=s,
            components={
                "spread_pct": abs(float(c.get("ask", 0) or 0) - float(c.get("bid", 0) or 0))
                              / max(0.5 * (float(c.get("bid", 0) or 0) + float(c.get("ask", 0) or 0)), 1e-9),
                "oi": float(c.get("open_interest", 0) or 0),
                "delta": float(c.get("delta", 0) or 0),
                "iv": float(c.get("implied_volatility", 0) or 0),
            },
        ))
    return sorted(scored, key=lambda x: x.score, reverse=True)


def sanity_check_analyst_strike(chain: list[dict], analyst_strike: float,
                                analyst_type: str, *, hv30: float | None = None,
                                predicted_hold_minutes: float | None = None) -> dict:
    """Return {'accepted': bool, 'reason': str, 'analyst_score': float, 'top_pick': ContractScore|None}.

    Accepts unless the analyst strike scores below the 25th percentile of the
    scanned chain (T6 mode 'b').
    """
    # Filter to ±STRIKE_RADIUS of analyst_strike, matching option_type
    nearby = [
        c for c in chain
        if str(c.get("option_type", "")).lower() == analyst_type.lower()
        and abs(float(c.get("strike", 0) or 0) - analyst_strike) <= STRIKE_RADIUS
    ]
    if not nearby:
        return {
            "accepted": True,
            "reason": "no_nearby_contracts_to_compare",
            "analyst_score": None,
            "top_pick": None,
        }

    scored = score_chain(nearby, hv30=hv30, predicted_hold_minutes=predicted_hold_minutes)
    scores = [s.score for s in scored]
    if not scores:
        return {"accepted": True, "reason": "empty_scores", "analyst_score": None, "top_pick": None}

    # Find analyst's contract in the scored list
    analyst_scored = next(
        (s for s in scored if abs(s.strike - analyst_strike) < 0.01), None
    )
    if analyst_scored is None:
        return {
            "accepted": True,
            "reason": "analyst_strike_not_in_chain",
            "analyst_score": None,
            "top_pick": scored[0].__dict__ if scored else None,
        }

    # Reject if analyst scores below the 25th percentile
    import numpy as np
    p25 = float(np.percentile(scores, ACCEPT_PERCENTILE * 100))
    if analyst_scored.score < p25:
        return {
            "accepted": False,
            "reason": f"analyst_score_{analyst_scored.score:.3f}_below_p25_{p25:.3f}",
            "analyst_score": analyst_scored.score,
            "top_pick": scored[0].__dict__,
        }

    return {
        "accepted": True,
        "reason": "analyst_strike_acceptable",
        "analyst_score": analyst_scored.score,
        "top_pick": scored[0].__dict__,
    }
