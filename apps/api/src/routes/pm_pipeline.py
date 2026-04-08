"""
Prediction Markets — LLM Pipeline endpoints (Phase 15.6 / F15-F).

POST /api/v2/pm/pipeline/score        — score a single market through full pipeline
GET  /api/v2/pm/pipeline/calibration  — Brier score + accuracy metrics
POST /api/v2/pm/pipeline/feedback     — record actual outcome for Brier tracking
GET  /api/v2/pm/pipeline/models       — list model evaluations
GET  /api/v2/pm/pipeline/config       — return current scorer config

Reference: docs/architecture/polymarket-phase15.md §8 Phase 15.6, §11
           docs/prd/polymarket-phase15.md F15-F (LLM Pipeline)
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import desc, select

from apps.api.src.deps import DbSession
from shared.db.models.polymarket import PMCalibrationSnapshot, PMModelEvaluation, PMTopBet

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/pm/pipeline", tags=["pm-pipeline"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class ScoreRequest(BaseModel):
    """Input for on-demand market scoring."""

    market_id: str | None = None  # UUID of an existing PMMarket record
    question: str | None = None  # Or provide a raw question text
    venue: str = "polymarket"
    yes_price: float | None = None
    no_price: float | None = None


class ScoreResult(BaseModel):
    question: str
    confidence_score: int
    side: str
    bull_argument: str | None
    bear_argument: str | None
    reference_class: str | None
    base_rate_yes: float | None
    edge_bps: int
    pipeline_version: str


class CalibrationMetrics(BaseModel):
    brier_score: float | None
    accuracy: float | None
    n_trades: int
    n_resolved: int
    sharpe: float | None
    window_days: int
    computed_at: str | None


class FeedbackRequest(BaseModel):
    market_id: str
    outcome: str  # "yes" | "no" | "n/a"
    notes: str | None = None


class ModelEvaluationEntry(BaseModel):
    id: str
    model_type: str
    brier_score: float
    accuracy: float
    sharpe_proxy: float | None
    num_markets_tested: int
    is_active: bool
    evaluated_at: str | None


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


@router.post("/score", response_model=ScoreResult)
async def score_market(
    payload: ScoreRequest,
    request: Request,
    db: DbSession,
) -> ScoreResult:
    """Score a single market through the full TopBets AI pipeline on-demand."""
    _require_user(request)

    if not payload.market_id and not payload.question:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either market_id or question",
        )

    market_dict: dict = {}
    question = payload.question or ""

    if payload.market_id:
        try:
            mid = uuid.UUID(payload.market_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid market_id UUID")

        from shared.db.models.polymarket import PMMarket  # local import to avoid circulars

        res = await db.execute(select(PMMarket).where(PMMarket.id == mid))
        market = res.scalar_one_or_none()
        if market is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Market not found")
        question = market.question
        market_dict = {
            "conditionId": str(market.id),
            "question": market.question,
            "category": market.category,
            "outcomes": market.outcomes or [],
        }
    else:
        market_dict = {
            "conditionId": str(uuid.uuid4()),
            "question": payload.question,
            "outcomes": [
                {"outcome": "Yes", "price": payload.yes_price or 0.5},
                {"outcome": "No", "price": payload.no_price or 0.5},
            ],
        }

    try:
        from agents.polymarket.top_bets.scorer import TopBetScorer  # type: ignore[import]

        scorer = TopBetScorer()
        results = await scorer.score_batch([market_dict], top_k=1)
        if results:
            sm = results[0]
            return ScoreResult(
                question=question,
                confidence_score=int(sm.final_score * 100),
                side=sm.llm_result.side if sm.llm_result and hasattr(sm.llm_result, "side") else "yes",
                bull_argument=getattr(sm.llm_result, "bull_argument", None) if sm.llm_result else None,
                bear_argument=getattr(sm.llm_result, "bear_argument", None) if sm.llm_result else None,
                reference_class=getattr(sm, "reference_class", None),
                base_rate_yes=getattr(sm, "base_rate_yes", None),
                edge_bps=int((sm.final_score - 0.5) * 200 * 100),
                pipeline_version="15.6",
            )
    except Exception as exc:
        logger.warning("pm.pipeline.score scorer unavailable: %s", exc)

    # Stub response when scorer is not available
    return ScoreResult(
        question=question,
        confidence_score=55,
        side="yes",
        bull_argument="Stub: scorer not available",
        bear_argument="Stub: scorer not available",
        reference_class=None,
        base_rate_yes=None,
        edge_bps=50,
        pipeline_version="15.6-stub",
    )


@router.get("/calibration", response_model=list[CalibrationMetrics])
async def get_calibration(
    request: Request,
    db: DbSession,
) -> list[CalibrationMetrics]:
    """Return Brier score and accuracy metrics from calibration snapshots."""
    _require_user(request)

    result = await db.execute(
        select(PMCalibrationSnapshot)
        .order_by(desc(PMCalibrationSnapshot.computed_at))
        .limit(10)
    )
    snapshots = result.scalars().all()

    return [
        CalibrationMetrics(
            brier_score=s.brier,
            accuracy=1.0 - s.brier if s.brier is not None else None,
            n_trades=s.n_trades,
            n_resolved=s.n_resolved,
            sharpe=s.sharpe,
            window_days=s.window_days,
            computed_at=s.computed_at.isoformat() if s.computed_at else None,
        )
        for s in snapshots
    ]


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def record_outcome_feedback(
    payload: FeedbackRequest,
    request: Request,
    db: DbSession,
) -> None:
    """Record the actual outcome of a market for Brier score recalculation."""
    _require_user(request)

    try:
        mid = uuid.UUID(payload.market_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid market_id UUID")

    result = await db.execute(select(PMTopBet).where(PMTopBet.market_id == mid).limit(1))
    bet = result.scalar_one_or_none()
    if bet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No top bet found for that market_id")

    outcome_note = f"[outcome:{payload.outcome}]"
    if payload.notes:
        outcome_note += f" {payload.notes[:200]}"
    bet.reasoning = (bet.reasoning or "") + f"\n{outcome_note}"
    db.add(bet)
    await db.commit()
    logger.info("pm.pipeline.feedback market_id=%s outcome=%s", payload.market_id, payload.outcome)


@router.get("/models", response_model=list[ModelEvaluationEntry])
async def list_model_evaluations(
    request: Request,
    db: DbSession,
) -> list[ModelEvaluationEntry]:
    """List all model evaluation records ordered by Brier score ascending (better = lower)."""
    _require_user(request)

    result = await db.execute(
        select(PMModelEvaluation)
        .order_by(PMModelEvaluation.brier_score.asc())
        .limit(50)
    )
    evals = result.scalars().all()

    return [
        ModelEvaluationEntry(
            id=str(e.id),
            model_type=e.model_type,
            brier_score=e.brier_score,
            accuracy=e.accuracy,
            sharpe_proxy=e.sharpe_proxy,
            num_markets_tested=e.num_markets_tested,
            is_active=e.is_active,
            evaluated_at=e.evaluated_at.isoformat() if e.evaluated_at else None,
        )
        for e in evals
    ]


@router.get("/config")
async def get_pipeline_config(request: Request) -> dict:
    """Return the current scorer configuration (read-only)."""
    _require_user(request)

    try:
        from pathlib import Path

        import yaml

        config_path = Path(__file__).parents[5] / "agents" / "polymarket" / "top_bets" / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                return {"config": yaml.safe_load(f), "source": str(config_path)}
    except Exception as exc:
        logger.debug("pm.pipeline.config: failed to load config.yaml: %s", exc)

    # Default config if file not found
    return {
        "config": {
            "min_confidence_threshold": 0.55,
            "top_k": 20,
            "cycle_interval_s": 60,
            "research_interval_s": 3600,
            "pipeline_version": "15.6",
        },
        "source": "defaults",
    }
