"""Centralised configuration for the TopBetsAgent (Phase 15.8).

All values are read from environment variables with sensible defaults so the
system works without any environment customisation.

Usage::

    from agents.polymarket.top_bets.config import TopBetsConfig

    cfg = TopBetsConfig.from_env()
    print(cfg.venue)           # "robinhood_predictions"
    print(cfg.cycle_interval_s)  # 60

Reference:
    docs/architecture/polymarket-phase15.md  §8 Phase 15.8
    docs/prd/polymarket-phase15.md           F15-A
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class TopBetsConfig:
    """Runtime configuration for the TopBetsAgent.

    All fields have sensible defaults so the agent can run without any env
    customisation during development / CI.

    Args:
        venue:             Venue registry key forwarded to :func:`get_venue`.
        cycle_interval_s:  Seconds between scan cycles.
        enabled:           Whether the agent should start automatically.
        debate_top_k:      Number of top markets to run the debate scorer on.
        cot_samples:       Number of chain-of-thought self-consistency samples.
    """

    venue: str = "robinhood_predictions"
    cycle_interval_s: int = 60
    enabled: bool = True
    debate_top_k: int = 5
    cot_samples: int = 5

    @classmethod
    def from_env(cls) -> "TopBetsConfig":
        """Build a :class:`TopBetsConfig` from environment variables.

        Environment variables
        ---------------------
        PM_TOP_BETS_VENUE
            Venue registry key (default: ``"robinhood_predictions"``).
        PM_TOP_BETS_CYCLE_INTERVAL_S
            Seconds between scan cycles (default: ``"60"``).
        PM_TOP_BETS_ENABLED
            Whether the agent should start (default: ``"true"``).

        Returns:
            Fully populated :class:`TopBetsConfig` instance.
        """
        return cls(
            venue=os.getenv("PM_TOP_BETS_VENUE", "robinhood_predictions"),
            cycle_interval_s=int(os.getenv("PM_TOP_BETS_CYCLE_INTERVAL_S", "60")),
            enabled=os.getenv("PM_TOP_BETS_ENABLED", "true").lower() == "true",
        )


__all__ = ["TopBetsConfig"]
