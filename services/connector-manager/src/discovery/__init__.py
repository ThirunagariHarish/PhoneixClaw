"""DiscoveryScanner package (Phase 4, Polymarket v1.0).

The scanner polls every registered `MarketVenue`, applies basic edge
filters (volume, time-to-resolution, spread), and upserts survivors
into `pm_markets`. Feature F2 in docs/architecture/polymarket-tab.md.
"""

from .scanner import (
    DEFAULT_MAX_DAYS_TO_RESOLUTION,
    DEFAULT_MIN_DAYS_TO_RESOLUTION,
    DEFAULT_MIN_VOLUME_USD,
    DiscoveryScanner,
    EdgeFilters,
    ScanCycleResult,
)

__all__ = [
    "DEFAULT_MAX_DAYS_TO_RESOLUTION",
    "DEFAULT_MIN_DAYS_TO_RESOLUTION",
    "DEFAULT_MIN_VOLUME_USD",
    "DiscoveryScanner",
    "EdgeFilters",
    "ScanCycleResult",
]
