"""cross_venue_arb (F3.2) — scaffold only.

Detects price spreads for the *same real-world event* listed on
Polymarket and a second venue (Kalshi in v1.x). Ships DISABLED in v1.0
because no Kalshi account exists yet.

The strategy is wired through the standard `MarketVenue` interface from
Phase 4 so activation in v1.x is a config flip + a real Kalshi venue
implementation; no code change in this folder is required for the
detector to start working.

See `docs/architecture/polymarket-tab.md` Phase 9.
"""

from .config import CrossVenueArbConfig, load_config
from .detector import (
    CrossVenueArbDetector,
    CrossVenueDisabledError,
    CrossVenueOpportunity,
)

__all__ = [
    "CrossVenueArbConfig",
    "load_config",
    "CrossVenueArbDetector",
    "CrossVenueOpportunity",
    "CrossVenueDisabledError",
]
