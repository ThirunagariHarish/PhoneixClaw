"""Decision fuser — combines ML prediction, TA, risk, and market status into a final decision."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Decision:
    action: str  # EXECUTE | WATCHLIST | REJECT
    final_confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)
    execution_params: Optional[dict] = None


def fuse(
    signal: dict,
    prediction: dict,
    risk: dict,
    ta: dict,
    market: dict,
    config: dict,
) -> Decision:
    """Fuse all pipeline outputs into a final trading decision.

    Args:
        signal: parsed signal dict (ticker, direction, etc.)
        prediction: ML prediction (prediction, confidence)
        risk: risk check result (approved, reason, checks)
        ta: TA result (overall_bias, confidence_adjustment, rsi, etc.)
        market: market status (is_open, session_type)
        config: agent config with risk_params
    """
    reasons: list[str] = []
    risk_params = config.get("risk_params", {})
    confidence_threshold = risk_params.get("confidence_threshold", 0.6)

    # Gate 1: Market closed → WATCHLIST
    if not market.get("is_open", False):
        session = market.get("session_type", "closed")
        reasons.append(f"Market {session} — deferring to watchlist")
        return Decision(
            action="WATCHLIST",
            final_confidence=float(prediction.get("confidence", 0.0)),
            reasons=reasons,
        )

    pred_action = prediction.get("prediction", "SKIP")
    pred_confidence = float(prediction.get("confidence", 0.0))

    # Gate 2: Model says SKIP with low confidence → WATCHLIST
    if pred_action == "SKIP" and pred_confidence < confidence_threshold:
        reasons.append(
            f"Model SKIP (confidence={pred_confidence:.3f} < {confidence_threshold})"
        )
        return Decision(
            action="WATCHLIST",
            final_confidence=pred_confidence,
            reasons=reasons,
        )

    # Gate 3: Risk rejected → REJECT
    if not risk.get("approved", False):
        reasons.append(f"Risk rejected: {risk.get('reason', 'unknown')}")
        return Decision(
            action="REJECT",
            final_confidence=pred_confidence,
            reasons=reasons,
        )

    # Gate 4: Model says SKIP (but confidence above threshold) → WATCHLIST
    if pred_action != "TRADE":
        reasons.append(f"Model {pred_action} — adding to watchlist")
        return Decision(
            action="WATCHLIST",
            final_confidence=pred_confidence,
            reasons=reasons,
        )

    # Model says TRADE and risk is approved — check TA alignment
    direction = signal.get("direction", "buy").lower()
    ta_bias = ta.get("overall_bias", "neutral")
    ta_adj = float(ta.get("confidence_adjustment", 0.0))

    ta_aligns = (
        (direction in ("buy", "long", "bto") and ta_bias == "bullish")
        or (direction in ("sell", "short", "stc") and ta_bias == "bearish")
    )
    ta_opposes = (
        (direction in ("buy", "long", "bto") and ta_bias == "bearish")
        or (direction in ("sell", "short", "stc") and ta_bias == "bullish")
    )

    if ta_aligns:
        final_confidence = min(1.0, pred_confidence + abs(ta_adj))
        reasons.append(f"TA confirms {ta_bias} — confidence boosted to {final_confidence:.3f}")
    elif ta_opposes:
        final_confidence = max(0.0, pred_confidence - abs(ta_adj))
        reasons.append(f"TA opposes ({ta_bias} vs {direction}) — downgraded to watchlist")
        return Decision(
            action="WATCHLIST",
            final_confidence=final_confidence,
            reasons=reasons,
        )
    else:
        final_confidence = pred_confidence
        reasons.append(f"TA neutral — proceeding at confidence {final_confidence:.3f}")

    # Build execution params
    ticker = signal.get("ticker", "")
    side = "buy" if direction in ("buy", "long", "bto") else "sell"
    qty = config.get("default_qty", 1)

    execution_params = {
        "symbol": ticker,
        "side": side,
        "order_type": "market",
        "qty": qty,
        "confidence": round(final_confidence, 4),
        "strike": signal.get("strike"),
        "expiry": signal.get("expiry"),
        "option_type": signal.get("option_type"),
    }

    reasons.append(f"EXECUTE: {side.upper()} {ticker} qty={qty}")
    return Decision(
        action="EXECUTE",
        final_confidence=round(final_confidence, 4),
        reasons=reasons,
        execution_params=execution_params,
    )
