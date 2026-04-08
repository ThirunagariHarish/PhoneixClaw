"""Pluggable market-venue interface (Phase 4, Polymarket v1.0).

A `MarketVenue` is a read-only metadata source for prediction markets that
the `DiscoveryScanner` can poll. v1.0 ships a Polymarket implementation
(backed by the Phase 2 GammaClient) and a Kalshi stub that raises
`NotConfiguredError` because the user has no Kalshi account.

Phase 15.2 adds `RobinhoodPredictionsVenue` — a paper-mode venue backed by
deterministic mock data (no public Robinhood Predictions API yet).

Reference: docs/architecture/polymarket-tab.md section 9 Phase 4.
Reference: docs/architecture/polymarket-phase15.md § 6, § 8.
"""

from .base import (
    MarketRow,
    MarketVenue,
    NotConfiguredError,
    VenueError,
    VenueScanResult,
)
from .kalshi_venue import KalshiVenue
from .polymarket_venue import PolymarketVenue
from .robinhood_predictions import RobinhoodPredictionsVenue

__all__ = [
    "KalshiVenue",
    "MarketRow",
    "MarketVenue",
    "NotConfiguredError",
    "PolymarketVenue",
    "RobinhoodPredictionsVenue",
    "VenueError",
    "VenueScanResult",
]
