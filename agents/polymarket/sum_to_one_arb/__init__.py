"""sum_to_one_arb — Polymarket binary-market YES+NO<1 arbitrage agent (Phase 8).

Reference: docs/architecture/polymarket-tab.md section 9, Phase 8 (F3.1).

This is the first real Polymarket strategy. It is paper-mode only in v1.0
per user policy. The agent:

  1. Scans `pm_markets` for binary markets where YES_ask + NO_ask < 1 - fees.
  2. Sizes paired BUY YES + BUY NO legs respecting `PolymarketLayerRisk`
     caps (per-trade, per-strategy, bankroll, kelly).
  3. Submits both legs through the injected risk-chain + broker
     (PolymarketBroker in PAPER mode by default).
  4. Records both orders with a shared `arb_group_id` via the injected
     order repository.
  5. Rolls back the first leg if the second leg fails to submit.
  6. Honors per-strategy `paused` flag and a global `kill_switch` callable
     so the orchestrator can halt the strategy in < 2s.

The agent's public surface is `SumToOneArbAgent`, exposed below for the
orchestrator loader to import. All collaborators (broker, risk chain,
order repo, market source, book source, clock) are injected so unit
tests can drive every branch with fakes.
"""

from .agent import (
    ArbOpportunity,
    ArbSubmission,
    KillSwitchTriggered,
    SumToOneArbAgent,
)
from .detector import SumToOneDetector
from .sizing import size_arb_legs

__all__ = [
    "ArbOpportunity",
    "ArbSubmission",
    "KillSwitchTriggered",
    "SumToOneArbAgent",
    "SumToOneDetector",
    "size_arb_legs",
]
