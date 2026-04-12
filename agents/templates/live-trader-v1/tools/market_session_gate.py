"""Route signals to watchlist when US regular session is closed.

Regular session: 9:30–16:00 ET (NYSE calendar in shared.utils.market_calendar).
Configurable via config.json or PHOENIX_WATCHLIST_OUTSIDE_RTH env.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from shared.utils.market_calendar import get_market_status, is_market_open

log = logging.getLogger(__name__)


def rth_watchlist_enabled(config: dict) -> bool:
    if config.get("watchlist_outside_regular_session") is not None:
        return bool(config["watchlist_outside_regular_session"])
    return os.getenv("PHOENIX_WATCHLIST_OUTSIDE_RTH", "true").lower() in ("1", "true", "yes")


def closed_market_watchlist_applies_to_direction(direction: str, config: dict) -> bool:
    """If True, defer this direction to watchlist when outside RTH."""
    if not config.get("closed_market_watchlist_buys_only", True):
        return True
    d = (direction or "").lower()
    return d in ("buy", "long", "bto")


def outside_rth_watchlist_payload(
    parsed: dict,
    config: dict,
    steps: list[dict],
    reasoning: list[str],
) -> dict[str, Any] | None:
    """If policy applies, mutate steps/reasoning and return payload for a WATCHLIST decision.

    Returns None when regular session is open or policy is disabled.
    """
    if is_market_open():
        return None
    if not rth_watchlist_enabled(config):
        return None
    direction = parsed.get("direction") or ""
    if not closed_market_watchlist_applies_to_direction(direction, config):
        return None

    status = get_market_status()
    steps.append({"step": "market_session", "status": "outside_regular", **status["step_meta"]})
    reasoning.append(status["summary"])
    reasoning.append("Outside regular session — ticker added to watchlist; no order placed.")

    ticker = (parsed.get("ticker") or "").strip().upper()
    if ticker:
        try:
            from paper_portfolio import _add_to_robinhood

            _add_to_robinhood(ticker)
            steps.append({"step": "robinhood_watchlist", "status": "ok", "ticker": ticker})
        except Exception as exc:
            log.debug("Robinhood watchlist add skipped: %s", exc)
            steps.append({"step": "robinhood_watchlist", "status": "skipped", "error": str(exc)[:120]})

    enriched = {**parsed, **status["features_flat"]}
    prediction = {
        "prediction": "DEFERRED",
        "confidence": 0.0,
        "pattern_matches": 0,
        "note": "outside_regular_session",
    }
    return {
        "reason": "outside_regular_session",
        "enriched": enriched,
        "prediction": prediction,
        "market_status": status,
    }
