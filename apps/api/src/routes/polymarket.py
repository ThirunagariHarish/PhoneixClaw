"""
Polymarket v1.0 — `/api/polymarket/*` HTTP routes (Phase 10).

Implements the 18 endpoints documented in `docs/architecture/polymarket-tab.md`
section 5. All endpoints require JWT auth (existing JWTAuthMiddleware sets
`request.state.user_id`); endpoints in this file enforce the presence of a
user via the `_require_user` helper.

Phase 10 deliberately ships thin handlers:

- Read endpoints query the PM ORM models via the existing async DB session.
- Write endpoints (promote/demote, kill switch, attest) record state through
  the same session.
- The promote endpoint defers to the Phase 11 `promotion_gate` engine if it
  is importable; otherwise it returns a TODO stub response so the API surface
  is wired and the dashboard (Phase 12) can integrate against it.
- The kill switch wires through to the existing `services/global-monitor`
  KillSwitch when importable, while keeping a PM-scoped local mirror so the
  /status endpoint always responds.

Reference: docs/architecture/polymarket-tab.md sections 5, 6.3, 6.4.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select

from apps.api.src.deps import DbSession
from shared.db.models.polymarket import (
    PMCalibrationSnapshot,
    PMJurisdictionAttestation,
    PMMarket,
    PMOrder,
    PMPosition,
    PMPromotionAudit,
    PMResolutionScore,
    PMStrategy,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/polymarket", tags=["polymarket"])


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _require_user(request: Request) -> str:
    """Return the JWT subject or raise 401.

    JWTAuthMiddleware already decoded the token; we just enforce presence.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth required")
    return str(user_id)


def _require_admin(request: Request) -> str:
    """Require an authenticated admin. Used for destructive PM operations."""
    user_id = _require_user(request)
    is_admin = bool(getattr(request.state, "is_admin", False))
    role = getattr(request.state, "role", None)
    if not (is_admin or role == "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")
    return user_id


def _user_uuid(user_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(user_id)
    except (ValueError, TypeError):
        return None


def _parse_uuid(raw: str, field: str = "id") -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"invalid {field}")


# ---------------------------------------------------------------------------
# PM-scoped kill switch state (in-process mirror; published to global on activate)
# ---------------------------------------------------------------------------


class _PMKillState:
    active: bool = False
    reason: str = ""
    activated_at: datetime | None = None


_pm_kill = _PMKillState()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class MarketRow(BaseModel):
    id: str
    venue: str
    venue_market_id: str
    slug: str | None = None
    question: str
    category: str | None = None
    outcomes: list[Any] = Field(default_factory=list)
    total_volume: float | None = None
    liquidity_usd: float | None = None
    expiry: datetime | None = None
    oracle_type: str | None = None
    is_active: bool = True
    last_scanned_at: datetime | None = None

    @classmethod
    def from_model(cls, m: PMMarket) -> "MarketRow":
        return cls(
            id=str(m.id),
            venue=m.venue,
            venue_market_id=m.venue_market_id,
            slug=m.slug,
            question=m.question,
            category=m.category,
            outcomes=list(m.outcomes or []),
            total_volume=m.total_volume,
            liquidity_usd=m.liquidity_usd,
            expiry=m.expiry,
            oracle_type=m.oracle_type,
            is_active=m.is_active,
            last_scanned_at=m.last_scanned_at,
        )


class ResolutionScoreOut(BaseModel):
    final_score: float | None = None
    tradeable: bool = False
    rationale: str | None = None
    oracle_type: str | None = None
    prior_disputes: int = 0
    scored_at: datetime | None = None


class MarketDetail(MarketRow):
    resolution_score: ResolutionScoreOut | None = None


class MarketsList(BaseModel):
    markets: list[MarketRow]
    total: int
    request_id: str


class ScanRequest(BaseModel):
    venue: str | None = None


class PMStrategyOut(BaseModel):
    id: str
    strategy_id: str
    archetype: str
    mode: str
    bankroll_usd: float
    max_strategy_notional_usd: float
    max_trade_notional_usd: float
    kelly_cap: float
    min_edge_bps: int | None = None
    paused: bool

    @classmethod
    def from_model(cls, s: PMStrategy) -> "PMStrategyOut":
        return cls(
            id=str(s.id),
            strategy_id=str(s.strategy_id),
            archetype=s.archetype,
            mode=s.mode,
            bankroll_usd=s.bankroll_usd,
            max_strategy_notional_usd=s.max_strategy_notional_usd,
            max_trade_notional_usd=s.max_trade_notional_usd,
            kelly_cap=s.kelly_cap,
            min_edge_bps=s.min_edge_bps,
            paused=s.paused,
        )


class PromoteRequest(BaseModel):
    typed_confirmation: str = Field(..., min_length=1)
    max_notional_first_week: float = Field(..., gt=0)
    ack_resolution_risk: bool


class DemoteRequest(BaseModel):
    reason: str | None = None


class AttestRequest(BaseModel):
    ack_geoblock: bool
    attestation_text_hash: str = Field(..., min_length=8, max_length=128)


class KillActivateRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class KillDeactivateRequest(BaseModel):
    typed_confirmation: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------


@router.get("/markets", response_model=MarketsList)
async def list_markets(
    request: Request,
    session: DbSession,
    category: str | None = None,
    min_volume: float | None = Query(None, ge=0),
    max_spread_bps: int | None = Query(None, ge=0),
    expiry_before: datetime | None = None,
    tradeable_only: bool = False,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> MarketsList:
    _require_user(request)

    q = select(PMMarket)
    if category:
        q = q.where(PMMarket.category == category)
    if min_volume is not None:
        q = q.where(PMMarket.total_volume >= min_volume)
    if expiry_before is not None:
        q = q.where(PMMarket.expiry <= expiry_before)
    q = q.order_by(desc(PMMarket.last_scanned_at)).limit(limit).offset(offset)

    res = await session.execute(q)
    rows = res.scalars().all()

    if tradeable_only and rows:
        ids = [m.id for m in rows]
        score_q = select(PMResolutionScore).where(
            PMResolutionScore.pm_market_id.in_(ids),
            PMResolutionScore.tradeable.is_(True),
        )
        sres = await session.execute(score_q)
        ok = {s.pm_market_id for s in sres.scalars().all()}
        rows = [m for m in rows if m.id in ok]

    total_q = select(func.count()).select_from(PMMarket)
    if category:
        total_q = total_q.where(PMMarket.category == category)
    total = (await session.execute(total_q)).scalar_one()

    return MarketsList(
        markets=[MarketRow.from_model(m) for m in rows],
        total=int(total or 0),
        request_id=str(uuid.uuid4()),
    )


@router.get("/markets/{market_id}", response_model=MarketDetail)
async def get_market(market_id: str, request: Request, session: DbSession) -> MarketDetail:
    _require_user(request)
    mid = _parse_uuid(market_id, "market_id")
    res = await session.execute(select(PMMarket).where(PMMarket.id == mid))
    m = res.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="market not found")

    sres = await session.execute(
        select(PMResolutionScore)
        .where(PMResolutionScore.pm_market_id == mid)
        .order_by(desc(PMResolutionScore.scored_at))
        .limit(1)
    )
    score = sres.scalar_one_or_none()
    base = MarketRow.from_model(m).model_dump()
    score_out = (
        ResolutionScoreOut(
            final_score=score.final_score,
            tradeable=score.tradeable,
            rationale=score.llm_rationale,
            oracle_type=score.oracle_type,
            prior_disputes=score.prior_disputes,
            scored_at=score.scored_at,
        )
        if score
        else None
    )
    return MarketDetail(**base, resolution_score=score_out)


@router.post("/markets/scan")
async def force_scan(payload: ScanRequest, request: Request) -> dict[str, Any]:
    _require_user(request)
    # Phase 4 owns the actual DiscoveryScanner; Phase 10 only exposes the hook.
    # Real implementation publishes to a Redis stream the scanner consumes.
    scan_id = uuid.uuid4()
    logger.info("pm.markets.scan requested venue=%s scan_id=%s", payload.venue, scan_id)
    return {"started": True, "scan_id": str(scan_id), "venue": payload.venue or "polymarket"}


@router.get("/markets/{market_id}/resolution-risk", response_model=ResolutionScoreOut)
async def get_resolution_risk(
    market_id: str, request: Request, session: DbSession
) -> ResolutionScoreOut:
    _require_user(request)
    mid = _parse_uuid(market_id, "market_id")
    res = await session.execute(
        select(PMResolutionScore)
        .where(PMResolutionScore.pm_market_id == mid)
        .order_by(desc(PMResolutionScore.scored_at))
        .limit(1)
    )
    score = res.scalar_one_or_none()
    if not score:
        raise HTTPException(status_code=404, detail="no resolution score for market")
    return ResolutionScoreOut(
        final_score=score.final_score,
        tradeable=score.tradeable,
        rationale=score.llm_rationale,
        oracle_type=score.oracle_type,
        prior_disputes=score.prior_disputes,
        scored_at=score.scored_at,
    )


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@router.get("/strategies", response_model=list[PMStrategyOut])
async def list_strategies(request: Request, session: DbSession) -> list[PMStrategyOut]:
    _require_user(request)
    res = await session.execute(select(PMStrategy).order_by(desc(PMStrategy.created_at)))
    return [PMStrategyOut.from_model(s) for s in res.scalars().all()]


@router.get("/strategies/{pm_strategy_id}", response_model=PMStrategyOut)
async def get_strategy(
    pm_strategy_id: str, request: Request, session: DbSession
) -> PMStrategyOut:
    _require_user(request)
    sid = _parse_uuid(pm_strategy_id, "pm_strategy_id")
    res = await session.execute(select(PMStrategy).where(PMStrategy.id == sid))
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="strategy not found")
    return PMStrategyOut.from_model(s)


async def _set_paused(
    session, pm_strategy_id: str, paused: bool, request: Request
) -> dict[str, Any]:
    _require_user(request)
    sid = _parse_uuid(pm_strategy_id, "pm_strategy_id")
    res = await session.execute(select(PMStrategy).where(PMStrategy.id == sid))
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="strategy not found")
    s.paused = paused
    await session.flush()
    return {"paused": s.paused, "id": str(s.id)}


@router.post("/strategies/{pm_strategy_id}/pause")
async def pause_strategy(
    pm_strategy_id: str, request: Request, session: DbSession
) -> dict[str, Any]:
    return await _set_paused(session, pm_strategy_id, True, request)


@router.post("/strategies/{pm_strategy_id}/resume")
async def resume_strategy(
    pm_strategy_id: str, request: Request, session: DbSession
) -> dict[str, Any]:
    return await _set_paused(session, pm_strategy_id, False, request)


@router.post("/strategies/{pm_strategy_id}/promote")
async def promote_strategy(
    pm_strategy_id: str,
    payload: PromoteRequest,
    request: Request,
    session: DbSession,
) -> dict[str, Any]:
    """Paper -> Live promotion gate.

    Re-validates every gate server-side regardless of client payload (per
    architecture §5/§6.3 and PRD §5). When the Phase 11 `promotion_gate`
    engine is importable, that is the single source of truth. Otherwise we
    return a structured TODO response and write an `attempt`/`failed` audit
    row so the surface is testable end-to-end before Phase 11 lands.
    """
    user_id = _require_user(request)
    sid = _parse_uuid(pm_strategy_id, "pm_strategy_id")
    res = await session.execute(select(PMStrategy).where(PMStrategy.id == sid))
    strat = res.scalar_one_or_none()
    if not strat:
        raise HTTPException(status_code=404, detail="strategy not found")

    if not payload.ack_resolution_risk:
        raise HTTPException(status_code=400, detail="ack_resolution_risk required")

    # M1: server-side typed-confirmation must equal the strategy archetype
    # (case-sensitive). Reject before any engine work.
    if payload.typed_confirmation != strat.archetype:
        raise HTTPException(
            status_code=400,
            detail="typed_confirmation must equal strategy archetype",
        )

    gate_evals: dict[str, Any]
    success: bool
    failure_reasons: list[str] = []
    try:
        from shared.polymarket.promotion_gate import (
            CalibrationRow,
            PromotionGateConfig,
            PromotionGateEngine,
            StrategySnapshot,
            TradeRow,
        )
    except Exception:  # pragma: no cover - defensive
        PromotionGateEngine = None  # type: ignore  # noqa: N806

    if PromotionGateEngine is not None:
        try:
            # B1: build a snapshot from the live DB session and run the real
            # PromotionGateEngine. Soak window is read from `paper_mode_since`
            # (M2), not `created_at`.
            cal_q = (
                select(PMCalibrationSnapshot)
                .where(PMCalibrationSnapshot.pm_strategy_id == strat.id)
                .order_by(desc(PMCalibrationSnapshot.computed_at))
                .limit(1)
            )
            cal_row = (await session.execute(cal_q)).scalar_one_or_none()
            calibration = (
                CalibrationRow(
                    n_trades=cal_row.n_trades or 0,
                    brier=cal_row.brier,
                    sharpe=cal_row.sharpe,
                    max_drawdown_pct=cal_row.max_drawdown_pct,
                    window_days=cal_row.window_days or 0,
                )
                if cal_row
                else None
            )

            ord_q = select(PMOrder).where(PMOrder.pm_strategy_id == strat.id)
            order_rows = (await session.execute(ord_q)).scalars().all()
            trades = [
                TradeRow(
                    submitted_at=o.submitted_at,
                    pm_market_id=o.pm_market_id,
                    f9_score=o.f9_score,
                )
                for o in order_rows
            ]
            f9_by_market: dict[uuid.UUID, float] = {}
            for o in order_rows:
                if o.f9_score is not None:
                    f9_by_market[o.pm_market_id] = float(o.f9_score)

            paper_since = getattr(strat, "paper_mode_since", None) or strat.created_at
            snapshot = StrategySnapshot(
                pm_strategy_id=strat.id,
                current_mode=strat.mode,
                created_at=paper_since,
                trades=trades,
                calibration=calibration,
                f9_scores_by_market=f9_by_market,
                last_successful_backtest_at=getattr(
                    strat, "last_successful_backtest_at", None
                ),
            )

            cfg = PromotionGateConfig(
                soak_days=7,
                min_trades=50,
                max_brier=0.20,
                min_sharpe=1.0,
                max_drawdown_pct=5.0,
                min_f9_score=0.70,
                max_backtest_age_days=30,
            )

            class _InlineProvider:
                def __init__(self, snap: StrategySnapshot) -> None:
                    self._snap = snap

                def load_snapshot(self, _id):
                    return self._snap

                def write_audit(self, **_kwargs):
                    return uuid.uuid4()

                def set_strategy_mode(self, _id, _mode):
                    return None

            engine = PromotionGateEngine(cfg, _InlineProvider(snapshot))
            result = engine.evaluate(strat.id)
            success = bool(result.passed)
            gate_evals = result.to_audit_payload()
            failure_reasons = list(result.failure_reasons)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("promotion_gate.evaluate failed: %s", exc)
            raise HTTPException(status_code=500, detail="promotion gate error") from exc
    else:
        success = False
        gate_evals = {
            "todo": {
                "passed": False,
                "reason": "promotion_gate engine not importable",
            }
        }

    audit = PMPromotionAudit(
        id=uuid.uuid4(),
        pm_strategy_id=strat.id,
        actor_user_id=_user_uuid(user_id),
        action="promote" if success else "attempt",
        outcome="success" if success else "failed",
        gate_evaluations=gate_evals,
        previous_mode=strat.mode,
        new_mode="LIVE" if success else strat.mode,
        notes=payload.typed_confirmation,
    )
    session.add(audit)
    if success:
        strat.mode = "LIVE"
    strat.last_promotion_attempt_id = audit.id
    await session.flush()

    return {
        "success": success,
        "audit_id": str(audit.id),
        "gate_evaluations": gate_evals,
        "failure_reasons": failure_reasons,
        "request_id": str(uuid.uuid4()),
    }


@router.post("/strategies/{pm_strategy_id}/demote")
async def demote_strategy(
    pm_strategy_id: str,
    payload: DemoteRequest,
    request: Request,
    session: DbSession,
) -> dict[str, Any]:
    user_id = _require_user(request)
    sid = _parse_uuid(pm_strategy_id, "pm_strategy_id")
    res = await session.execute(select(PMStrategy).where(PMStrategy.id == sid))
    strat = res.scalar_one_or_none()
    if not strat:
        raise HTTPException(status_code=404, detail="strategy not found")

    prev = strat.mode
    strat.mode = "PAPER"
    # M2: reset soak baseline whenever a strategy returns to PAPER, so the
    # promotion gate measures soak from the most recent demotion (or initial
    # creation), not from the original strategy creation timestamp.
    if hasattr(strat, "paper_mode_since"):
        strat.paper_mode_since = datetime.now(timezone.utc)
    audit = PMPromotionAudit(
        id=uuid.uuid4(),
        pm_strategy_id=strat.id,
        actor_user_id=_user_uuid(user_id),
        action="demote",
        outcome="success",
        gate_evaluations={"reason": payload.reason or "manual"},
        previous_mode=prev,
        new_mode="PAPER",
        notes=payload.reason,
    )
    session.add(audit)
    await session.flush()
    return {"success": True, "audit_id": str(audit.id)}


@router.get("/strategies/{pm_strategy_id}/promotion_audit")
async def list_promotion_audit(
    pm_strategy_id: str, request: Request, session: DbSession
) -> list[dict[str, Any]]:
    _require_user(request)
    sid = _parse_uuid(pm_strategy_id, "pm_strategy_id")
    res = await session.execute(
        select(PMPromotionAudit)
        .where(PMPromotionAudit.pm_strategy_id == sid)
        .order_by(desc(PMPromotionAudit.created_at))
    )
    return [
        {
            "id": str(a.id),
            "action": a.action,
            "outcome": a.outcome,
            "previous_mode": a.previous_mode,
            "new_mode": a.new_mode,
            "gate_evaluations": a.gate_evaluations or {},
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in res.scalars().all()
    ]


@router.get("/strategies/{pm_strategy_id}/calibration")
async def get_calibration(
    pm_strategy_id: str,
    request: Request,
    session: DbSession,
    window_days: int = Query(30, ge=1, le=365),
    category: str | None = None,
) -> dict[str, Any]:
    _require_user(request)
    sid = _parse_uuid(pm_strategy_id, "pm_strategy_id")
    q = (
        select(PMCalibrationSnapshot)
        .where(
            PMCalibrationSnapshot.pm_strategy_id == sid,
            PMCalibrationSnapshot.window_days == window_days,
        )
        .order_by(desc(PMCalibrationSnapshot.computed_at))
        .limit(1)
    )
    if category:
        q = q.where(PMCalibrationSnapshot.category == category)
    res = await session.execute(q)
    snap = res.scalar_one_or_none()
    if not snap:
        return {"available": False}
    return {
        "available": True,
        "n_trades": snap.n_trades,
        "n_resolved": snap.n_resolved,
        "brier": snap.brier,
        "log_loss": snap.log_loss,
        "sharpe": snap.sharpe,
        "max_drawdown_pct": snap.max_drawdown_pct,
        "reliability_bins": snap.reliability_bins or [],
        "computed_at": snap.computed_at.isoformat() if snap.computed_at else None,
    }


# ---------------------------------------------------------------------------
# Orders & positions
# ---------------------------------------------------------------------------


@router.get("/orders")
async def list_orders(
    request: Request,
    session: DbSession,
    strategy_id: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict[str, Any]]:
    _require_user(request)
    q = select(PMOrder).order_by(desc(PMOrder.submitted_at)).limit(limit)
    if strategy_id:
        q = q.where(PMOrder.pm_strategy_id == _parse_uuid(strategy_id, "strategy_id"))
    if status_filter:
        q = q.where(PMOrder.status == status_filter)
    res = await session.execute(q)
    return [
        {
            "id": str(o.id),
            "pm_strategy_id": str(o.pm_strategy_id),
            "pm_market_id": str(o.pm_market_id),
            "outcome_token_id": o.outcome_token_id,
            "side": o.side,
            "qty_shares": o.qty_shares,
            "limit_price": o.limit_price,
            "mode": o.mode,
            "status": o.status,
            "venue_order_id": o.venue_order_id,
            "fees_paid_usd": o.fees_paid_usd,
            "slippage_bps": o.slippage_bps,
            "f9_score": o.f9_score,
            "arb_group_id": str(o.arb_group_id) if o.arb_group_id else None,
            "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
            "filled_at": o.filled_at.isoformat() if o.filled_at else None,
            "cancelled_at": o.cancelled_at.isoformat() if o.cancelled_at else None,
        }
        for o in res.scalars().all()
    ]


@router.get("/positions")
async def list_positions(
    request: Request,
    session: DbSession,
    mode: str | None = Query(None, pattern="^(PAPER|LIVE)$"),
    strategy_id: str | None = None,
) -> list[dict[str, Any]]:
    _require_user(request)
    q = select(PMPosition).order_by(desc(PMPosition.opened_at))
    if mode:
        q = q.where(PMPosition.mode == mode)
    if strategy_id:
        q = q.where(PMPosition.pm_strategy_id == _parse_uuid(strategy_id, "strategy_id"))
    res = await session.execute(q)
    return [
        {
            "id": str(p.id),
            "pm_strategy_id": str(p.pm_strategy_id),
            "pm_market_id": str(p.pm_market_id),
            "outcome_token_id": p.outcome_token_id,
            "qty_shares": p.qty_shares,
            "avg_entry_price": p.avg_entry_price,
            "mode": p.mode,
            "unrealized_pnl_usd": p.unrealized_pnl_usd,
            "realized_pnl_usd": p.realized_pnl_usd,
            "opened_at": p.opened_at.isoformat() if p.opened_at else None,
            "closed_at": p.closed_at.isoformat() if p.closed_at else None,
        }
        for p in res.scalars().all()
    ]


# ---------------------------------------------------------------------------
# Jurisdiction attestation
# ---------------------------------------------------------------------------


_ATTESTATION_TTL_DAYS = 30


@router.post("/jurisdiction/attest")
async def submit_attestation(
    payload: AttestRequest, request: Request, session: DbSession
) -> dict[str, Any]:
    user_id = _require_user(request)
    if not payload.ack_geoblock:
        raise HTTPException(status_code=400, detail="ack_geoblock must be true")

    user_uuid = _user_uuid(user_id)
    if user_uuid is None:
        raise HTTPException(status_code=400, detail="invalid user identity")

    valid_until = datetime.now(timezone.utc) + timedelta(days=_ATTESTATION_TTL_DAYS)
    # Defensive: hash the hash again so the stored value is bounded.
    hashed = hashlib.sha256(payload.attestation_text_hash.encode("utf-8")).hexdigest()

    att = PMJurisdictionAttestation(
        id=uuid.uuid4(),
        user_id=user_uuid,
        attestation_text_hash=hashed,
        acknowledged_geoblock=True,
        ip_at_attestation=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        valid_until=valid_until,
    )
    session.add(att)
    await session.flush()
    return {"id": str(att.id), "valid_until": valid_until.isoformat()}


@router.get("/jurisdiction/current")
async def current_attestation(request: Request, session: DbSession) -> dict[str, Any]:
    user_id = _require_user(request)
    user_uuid = _user_uuid(user_id)
    if user_uuid is None:
        return {"valid": False}
    res = await session.execute(
        select(PMJurisdictionAttestation)
        .where(PMJurisdictionAttestation.user_id == user_uuid)
        .order_by(desc(PMJurisdictionAttestation.created_at))
        .limit(1)
    )
    att = res.scalar_one_or_none()
    if not att:
        return {"valid": False}
    now = datetime.now(timezone.utc)
    valid_until = att.valid_until
    if valid_until is not None and valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=timezone.utc)
    valid = bool(att.acknowledged_geoblock and valid_until and valid_until > now)
    return {"valid": valid, "valid_until": valid_until.isoformat() if valid_until else None}


# ---------------------------------------------------------------------------
# Kill switch (PM-scoped, propagates to global if available)
# ---------------------------------------------------------------------------


async def _publish_global_kill(action: str, reason: str) -> None:
    """Best-effort propagation to the global monitor kill switch.

    Phase 10 keeps this loosely coupled. The global-monitor service is the
    authoritative subscriber via `stream:kill-switch`; if Redis is not
    available the local mirror still reflects PM state for /status.
    """
    try:
        from services.global_monitor.src.kill_switch import KillSwitch  # type: ignore
    except Exception:
        return
    try:
        ks = KillSwitch()
        if action == "activate":
            await ks.activate(reason)
        else:
            deactivate = getattr(ks, "deactivate", None)
            if deactivate is not None:
                await deactivate()
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("global kill switch propagation failed: %s", exc)


@router.post("/kill-switch/activate")
async def kill_switch_activate(
    payload: KillActivateRequest, request: Request
) -> dict[str, Any]:
    _require_user(request)
    _pm_kill.active = True
    _pm_kill.reason = payload.reason
    _pm_kill.activated_at = datetime.now(timezone.utc)
    await _publish_global_kill("activate", f"polymarket: {payload.reason}")
    return {
        "active": True,
        "reason": _pm_kill.reason,
        "activated_at": _pm_kill.activated_at.isoformat(),
        "scope": "polymarket",
    }


@router.post("/kill-switch/deactivate")
async def kill_switch_deactivate(
    payload: KillDeactivateRequest, request: Request
) -> dict[str, Any]:
    # M8: deactivating the PM kill switch is destructive — admin only.
    _require_admin(request)
    if payload.typed_confirmation.strip().upper() != "REARM":
        raise HTTPException(
            status_code=400, detail="typed_confirmation must equal 'REARM'"
        )
    _pm_kill.active = False
    _pm_kill.reason = ""
    _pm_kill.activated_at = None
    await _publish_global_kill("deactivate", "polymarket rearm")
    return {"active": False, "scope": "polymarket"}


@router.get("/kill-switch/status")
async def kill_switch_status(request: Request) -> dict[str, Any]:
    _require_user(request)
    return {
        "active": _pm_kill.active,
        "reason": _pm_kill.reason or None,
        "activated_at": _pm_kill.activated_at.isoformat() if _pm_kill.activated_at else None,
        "scope": "polymarket",
    }


# ---------------------------------------------------------------------------
# Briefing section (Phase 13 owns the compiler; this is a passthrough stub)
# ---------------------------------------------------------------------------


@router.get("/briefing/section")
async def briefing_section(
    request: Request,
    session: DbSession,
    date: str | None = None,
) -> dict[str, Any]:
    _require_user(request)
    # Phase 13 will replace this with the real compile_pm_section call.
    paper_pnl = 0.0
    live_pnl = 0.0
    try:
        res = await session.execute(select(PMPosition))
        for p in res.scalars().all():
            pnl = (p.realized_pnl_usd or 0.0) + (p.unrealized_pnl_usd or 0.0)
            if p.mode == "LIVE":
                live_pnl += pnl
            else:
                paper_pnl += pnl
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("briefing section pnl read failed: %s", exc)

    return {
        "date": date,
        "movers": [],
        "new_high_volume": [],
        "resolutions_24h": [],
        "f9_risks": [],
        "paper_pnl": paper_pnl,
        "live_pnl": live_pnl,
        "kill_switch": {
            "active": _pm_kill.active,
            "reason": _pm_kill.reason or None,
        },
    }
