"""
Prediction Markets — Venue endpoints (Phase 15.6 / F15-E).

GET  /api/v2/pm/venues                       — list available venues with status
GET  /api/v2/pm/venues/{venue}/markets       — fetch live markets from venue
POST /api/v2/pm/venues/{venue}/sync          — sync venue markets to pm_historical_markets

Reference: docs/architecture/polymarket-phase15.md §8 Phase 15.6, §6 Venue Registry
           docs/prd/polymarket-phase15.md F15-E (Venues)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert

from apps.api.src.deps import DbSession
from shared.db.models.polymarket import PMHistoricalMarket

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/pm/venues", tags=["pm-venues"])

# Supported venues and their display metadata
_VENUE_META: dict[str, dict] = {
    "polymarket": {
        "display_name": "Polymarket",
        "status": "active",
        "description": "Decentralised prediction market on Polygon",
        "supports_live_trading": False,
    },
    "robinhood_predictions": {
        "display_name": "Robinhood Predictions",
        "status": "active",
        "description": "Robinhood brokerage event contracts",
        "supports_live_trading": False,
    },
    "kalshi": {
        "display_name": "Kalshi",
        "status": "coming_soon",
        "description": "CFTC-regulated event contracts",
        "supports_live_trading": False,
    },
}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class VenueInfo(BaseModel):
    name: str
    display_name: str
    status: str  # active | coming_soon | error
    description: str
    supports_live_trading: bool


class MarketEntry(BaseModel):
    venue_market_id: str
    question: str
    category: str | None
    yes_price: float | None
    no_price: float | None
    volume_usd: float | None
    liquidity_usd: float | None


class SyncResult(BaseModel):
    venue: str
    markets_synced: int
    errors: int


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _require_user(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth required")
    return str(user_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[VenueInfo])
async def list_venues(request: Request) -> list[VenueInfo]:
    """List all known prediction market venues and their availability."""
    _require_user(request)

    result: list[VenueInfo] = []
    for name, meta in _VENUE_META.items():
        # Probe the venue to confirm it's importable when status is active
        venue_status = meta["status"]
        if venue_status == "active":
            try:
                from shared.polymarket.venue_registry import get_venue  # type: ignore[import]

                get_venue(name)
            except Exception:
                venue_status = "error"

        result.append(
            VenueInfo(
                name=name,
                display_name=meta["display_name"],
                status=venue_status,
                description=meta["description"],
                supports_live_trading=meta["supports_live_trading"],
            )
        )
    return result


@router.get("/{venue}/markets", response_model=list[MarketEntry])
async def list_venue_markets(
    venue: str,
    request: Request,
    limit: int = 50,
) -> list[MarketEntry]:
    """Fetch live markets directly from the specified venue."""
    _require_user(request)

    if venue not in _VENUE_META:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown venue: {venue!r}")

    if _VENUE_META[venue]["status"] == "coming_soon":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Venue {venue!r} coming soon")

    try:
        from shared.polymarket.venue_registry import get_venue  # type: ignore[import]

        v = get_venue(venue)
        raw_markets = await v.fetch_markets(limit=limit)  # type: ignore[attr-defined]
    except Exception as exc:
        logger.error("pm.venues.markets venue=%s error=%s", venue, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Failed to fetch markets: {exc}") from exc

    result: list[MarketEntry] = []
    for m in raw_markets:
        if not isinstance(m, dict):
            continue
        yes_price: float | None = None
        no_price: float | None = None
        outcomes = m.get("outcomes") or m.get("tokens") or []
        for o in outcomes:
            if not isinstance(o, dict):
                continue
            label = (o.get("outcome") or o.get("label") or o.get("name") or "").lower()
            price = o.get("price") or o.get("probability")
            if price is not None:
                try:
                    pf = float(price)
                except (TypeError, ValueError):
                    pf = None
                if "yes" in label:
                    yes_price = pf
                elif "no" in label:
                    no_price = pf

        result.append(
            MarketEntry(
                venue_market_id=str(m.get("conditionId") or m.get("id") or m.get("market_id") or ""),
                question=str(m.get("question") or m.get("title") or ""),
                category=m.get("category"),
                yes_price=yes_price,
                no_price=no_price,
                volume_usd=m.get("volumeNum") or m.get("volume"),
                liquidity_usd=m.get("liquidity") or m.get("liquidityNum"),
            )
        )
    return result


@router.post("/{venue}/sync", response_model=SyncResult)
async def sync_venue_markets(
    venue: str,
    request: Request,
    db: DbSession,
) -> SyncResult:
    """Fetch live markets from a venue and upsert them into pm_historical_markets."""
    _require_user(request)

    if venue not in _VENUE_META:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown venue: {venue!r}")

    if _VENUE_META[venue]["status"] == "coming_soon":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Venue {venue!r} coming soon")

    try:
        from shared.polymarket.venue_registry import get_venue  # type: ignore[import]

        v = get_venue(venue)
        raw_markets = await v.fetch_markets(limit=200)  # type: ignore[attr-defined]
    except Exception as exc:
        logger.error("pm.venues.sync fetch failed venue=%s: %s", venue, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    synced = 0
    errors = 0
    for m in raw_markets:
        if not isinstance(m, dict):
            continue
        try:
            venue_market_id = str(m.get("conditionId") or m.get("id") or m.get("market_id") or "")
            if not venue_market_id:
                continue
            question = str(m.get("question") or m.get("title") or "")
            stmt = pg_insert(PMHistoricalMarket).values(
                id=uuid.uuid4(),
                venue=venue,
                venue_market_id=venue_market_id,
                question=question,
                category=m.get("category"),
                description=m.get("description"),
                volume_usd=m.get("volumeNum") or m.get("volume"),
                liquidity_peak_usd=m.get("liquidity"),
                updated_at=datetime.now(timezone.utc),
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_pm_historical_markets_venue_id",
                set_={
                    "question": stmt.excluded.question,
                    "category": stmt.excluded.category,
                    "volume_usd": stmt.excluded.volume_usd,
                    "liquidity_peak_usd": stmt.excluded.liquidity_peak_usd,
                    "updated_at": stmt.excluded.updated_at,
                },
            )
            await db.execute(stmt)
            synced += 1
        except Exception as exc:
            logger.warning("pm.venues.sync upsert error venue=%s: %s", venue, exc)
            errors += 1

    await db.commit()
    logger.info("pm.venues.sync venue=%s synced=%d errors=%d", venue, synced, errors)
    return SyncResult(venue=venue, markets_synced=synced, errors=errors)
