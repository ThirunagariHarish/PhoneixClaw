"""Shared Polymarket primitives.

Phase 1 ships only the jurisdiction attestation gate. Later phases add
fees, bankroll, resolution_risk, promotion_gate, and event topics.
"""

from shared.polymarket.events import (
    PM_BOOKS_STREAM,
    PM_MARKETS_STREAM,
    PM_RESYNC_STREAM,
    PM_RTDS_STATUS_STREAM,
)
from shared.polymarket.jurisdiction import (
    AttestationState,
    JurisdictionAttestationGate,
    JurisdictionGateError,
)
from shared.polymarket.resolution_risk import (
    MarketInput,
    ResolutionRiskFactors,
    ResolutionRiskResult,
    ResolutionRiskScorer,
)

__all__ = [
    "AttestationState",
    "JurisdictionAttestationGate",
    "JurisdictionGateError",
    "MarketInput",
    "PM_BOOKS_STREAM",
    "PM_MARKETS_STREAM",
    "PM_RESYNC_STREAM",
    "PM_RTDS_STATUS_STREAM",
    "ResolutionRiskFactors",
    "ResolutionRiskResult",
    "ResolutionRiskScorer",
]
