"""Prediction-market venue registry (Phase 15.2).

Provides a central, string-keyed registry of all known `MarketVenue`
implementations so higher-level code can select a venue by name without
hard-coding imports.

Imports are deferred to `get_venue()` call time to keep module-load
overhead minimal and avoid circular-import issues between `shared` and
`services`.

Usage::

    from shared.polymarket.venue_registry import get_venue

    venue = get_venue("robinhood_predictions")
    markets = await venue.fetch_markets(limit=20)

Reference: docs/architecture/polymarket-phase15.md § 6, § 8.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.connector_manager.src.venues.base import MarketVenue


def _registry() -> dict[str, type]:
    """Build the venue registry with deferred imports.

    Deferred so that importing this module does not cascade through
    GammaClient → polymarket adapter → shared.db at import time.
    """
    from services.connector_manager.src.venues.polymarket_venue import PolymarketVenue
    from services.connector_manager.src.venues.robinhood_predictions import RobinhoodPredictionsVenue

    return {
        "robinhood_predictions": RobinhoodPredictionsVenue,
        "polymarket": PolymarketVenue,
    }


#: Eagerly-resolved registry used for introspection / iteration.
#  Populated lazily on first access via `get_venue` or explicit import.
VENUE_REGISTRY: dict[str, type] = {}


def get_venue(name: str) -> MarketVenue:
    """Instantiate and return a venue by name.

    Args:
        name: Venue identifier string, e.g. ``"robinhood_predictions"`` or
              ``"polymarket"``.

    Returns:
        A freshly constructed `MarketVenue` instance.

    Raises:
        ValueError: if *name* is not registered.
    """
    # Build (or refresh) the registry on first call.
    global VENUE_REGISTRY  # noqa: PLW0603
    if not VENUE_REGISTRY:
        VENUE_REGISTRY.update(_registry())

    cls = VENUE_REGISTRY.get(name)
    if cls is None:
        known = ", ".join(sorted(VENUE_REGISTRY.keys()))
        raise ValueError(f"Unknown venue: {name!r}. Known venues: {known}")
    return cls()  # type: ignore[return-value]
