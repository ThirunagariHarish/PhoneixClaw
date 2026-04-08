"""
Prediction Markets — Top Bets endpoints (Phase 15.6).

GET  /api/v2/pm/top-bets              — list top bets (paginated, filterable by venue/category)
GET  /api/v2/pm/top-bets/summary      — aggregated stats
GET  /api/v2/pm/top-bets/{bet_id}     — single top bet with full scorer details
POST /api/v2/pm/top-bets/{bet_id}/execute  — paper order execution
PUT  /api/v2/pm/top-bets/{bet_id}/feedback — user feedback (thumbs up/down)

Reference: docs/architecture/polymarket-phase15.md §8 Phase 15.6, §11 API Contracts
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from apps.api.src.deps import DbSession
from shared.db.models.polymarket import PMMarket, PMTopBet

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/pm/top-bets", tags=["pm-top-bets"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TopBetResponse(BaseModel):
    id: str
    market_id: str
    venue: str
    question: str
    yes_probability: float | None
    no_probability: float | None
    confidence_score: int
    side: str
    bull_argument: str | None
    bear_argument: str | None
    reference_class: str | None
    base_rate_yes: float | None
    status: str
    last_updated_at: str


class TopBetSummaryResponse(BaseModel):
    total_active: int
    avg_confidence: float
    top_category: str | None
    venues_active: list[str]


class ExecuteOrderRequest(BaseModel):
    amount_usd: float = Field(..., ge=1.0, le=1000.0)
    side: Literal["yes", "no"]


class ExecuteOrderResponse(BaseModel):
    order_id: str
    status: str
    amount_usd: float
    side: str
    venue: str
    paper: bool = True


class FeedbackRequest(BaseModel):
    thumbs: Literal["up", "down"]
    comment: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_user(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth required")
    return str(user_id)


def _bet_to_response(bet: PMTopBet, market: PMMarket | None) -> TopBetResponse:
    yes_prob: float | None = None
    no_prob: float | None = None
    venue = "polymarket"
    question = ""
    if market:
        venue = market.venue
        question = market.question
        outcomes = market.outcomes or []
        for o in outcomes:
            if isinstance(o, dict):
                label = (o.get("label") or o.get("name") or "").lower()
                price = o.get("price") or o.get("probability")
                if price is not None:
                    try:
                        price_f = float(price)
                    except (TypeError, ValueError):
                        price_f = None
                    if "yes" in label:
                        yes_prob = price_f
                    elif "no" in label:
                        no_prob = price_f
    return TopBetResponse(
        id=str(bet.id),
        market_id=str(bet.market_id),
        venue=venue,
        question=question,
        yes_probability=yes_prob,
        no_probability=no_prob,
        confidence_score=bet.confidence_score,
        side=bet.side,
        bull_argument=bet.bull_argument,
        bear_argument=bet.bear_argument,
        reference_class=bet.reference_class,
        base_rate_yes=bet.base_rate_yes,
        status=bet.status,
        last_updated_at=bet.updated_at.isoformat() if bet.updated_at else "",
    )


# ---------------------------------------------------------------------------
# NOTE: /summary must appear BEFORE /{bet_id} to avoid routing ambiguity
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=TopBetSummaryResponse)
async def get_top_bets_summary(
    request: Request,
    db: DbSession,
) -> TopBetSummaryResponse:
    """Aggregated stats for active top bets."""
    _require_user(request)

    result = await db.execute(
        select(PMTopBet).where(PMTopBet.status == "pending").limit(200)
    )
    bets = result.scalars().all()

    if not bets:
        return TopBetSummaryResponse(total_active=0, avg_confidence=0.0, top_category=None, venues_active=[])

    market_ids = list({b.market_id for b in bets})
    market_result = await db.execute(
        select(PMMarket).where(PMMarket.id.in_(market_ids))
    )
    markets = {m.id: m for m in market_result.scalars().all()}

    venue_set: set[str] = set()
    category_counts: dict[str, int] = {}
    for bet in bets:
        m = markets.get(bet.market_id)
        if m:
            venue_set.add(m.venue)
            if m.category:
                category_counts[m.category] = category_counts.get(m.category, 0) + 1

    avg_conf = round(sum(b.confidence_score for b in bets) / len(bets), 2) if bets else 0.0
    top_category = max(category_counts, key=category_counts.get) if category_counts else None  # type: ignore[arg-type]

    return TopBetSummaryResponse(
        total_active=len(bets),
        avg_confidence=avg_conf,
        top_category=top_category,
        venues_active=sorted(venue_set),
    )


@router.get("", response_model=list[TopBetResponse])
async def list_top_bets(
    request: Request,
    db: DbSession,
    venue: str | None = Query(None, description="Filter by venue slug"),
    category: str | None = Query(None, description="Filter by market category"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> list[TopBetResponse]:
    """List top bets with optional venue / category filter, paginated."""
    _require_user(request)

    stmt = select(PMTopBet).where(PMTopBet.status == "pending")

    if venue or category:
        market_stmt = select(PMMarket)
        if venue:
            market_stmt = market_stmt.where(PMMarket.venue == venue)
        if category:
            market_stmt = market_stmt.where(PMMarket.category == category)
        mresult = await db.execute(market_stmt)
        filtered_market_ids = [m.id for m in mresult.scalars().all()]
        if not filtered_market_ids:
            return []
        stmt = stmt.where(PMTopBet.market_id.in_(filtered_market_ids))

    stmt = stmt.order_by(PMTopBet.confidence_score.desc()).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(stmt)
    bets = result.scalars().all()

    if not bets:
        return []

    market_ids = [b.market_id for b in bets]
    mres = await db.execute(select(PMMarket).where(PMMarket.id.in_(market_ids)))
    markets = {m.id: m for m in mres.scalars().all()}

    return [_bet_to_response(b, markets.get(b.market_id)) for b in bets]


@router.get("/{bet_id}", response_model=TopBetResponse)
async def get_top_bet(
    bet_id: str,
    request: Request,
    db: DbSession,
) -> TopBetResponse:
    """Fetch a single top bet by ID with full scorer details."""
    _require_user(request)

    try:
        bet_uuid = uuid.UUID(bet_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid bet_id UUID")

    result = await db.execute(select(PMTopBet).where(PMTopBet.id == bet_uuid))
    bet: PMTopBet | None = result.scalar_one_or_none()
    if bet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Top bet not found")

    mres = await db.execute(select(PMMarket).where(PMMarket.id == bet.market_id))
    market: PMMarket | None = mres.scalar_one_or_none()

    return _bet_to_response(bet, market)


@router.post("/{bet_id}/execute", response_model=ExecuteOrderResponse)
async def execute_order(
    bet_id: str,
    payload: ExecuteOrderRequest,
    request: Request,
    db: DbSession,
) -> ExecuteOrderResponse:
    """Place a paper order for a top bet.  Live execution deferred to Phase 16."""
    _require_user(request)

    try:
        bet_uuid = uuid.UUID(bet_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid bet_id UUID")

    result = await db.execute(select(PMTopBet).where(PMTopBet.id == bet_uuid))
    bet: PMTopBet | None = result.scalar_one_or_none()
    if bet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Top bet not found")

    mres = await db.execute(select(PMMarket).where(PMMarket.id == bet.market_id))
    market: PMMarket | None = mres.scalar_one_or_none()
    venue_name = market.venue if market else "polymarket"

    order_id = str(uuid.uuid4())
    logger.info(
        "pm.top_bets.paper_order bet_id=%s side=%s amount_usd=%.2f venue=%s order_id=%s",
        bet_id,
        payload.side,
        payload.amount_usd,
        venue_name,
        order_id,
    )

    return ExecuteOrderResponse(
        order_id=order_id,
        status="accepted",
        amount_usd=payload.amount_usd,
        side=payload.side,
        venue=venue_name,
        paper=True,
    )


@router.put("/{bet_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def submit_feedback(
    bet_id: str,
    payload: FeedbackRequest,
    request: Request,
    db: DbSession,
) -> None:
    """Record user thumbs-up / thumbs-down feedback on a bet recommendation."""
    _require_user(request)

    try:
        bet_uuid = uuid.UUID(bet_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid bet_id UUID")

    result = await db.execute(select(PMTopBet).where(PMTopBet.id == bet_uuid))
    bet: PMTopBet | None = result.scalar_one_or_none()
    if bet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Top bet not found")

    # Persist feedback in reasoning field as a structured note (lightweight — no dedicated feedback table yet)
    note = f"[feedback:{payload.thumbs}]"
    if payload.comment:
        note += f" {payload.comment[:200]}"
    bet.reasoning = (bet.reasoning or "") + f"\n{note}"
    db.add(bet)
    await db.commit()
    logger.info("pm.top_bets.feedback bet_id=%s thumbs=%s", bet_id, payload.thumbs)
