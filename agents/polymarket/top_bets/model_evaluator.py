"""Model Evaluator — tracks prediction accuracy and Brier scores (Phase 15.4).

Persists running-average model evaluation metrics in :class:`PMModelEvaluation`.
Uses a running incremental update so individual predictions never need to be
replayed; the aggregate row is the single source of truth.

Reference:
    docs/architecture/polymarket-phase15.md  § 9 (Scorer Chain)
    docs/prd/polymarket-phase15.md           F15-F
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.polymarket import PMModelEvaluation

logger = logging.getLogger(__name__)


class ModelEvaluator:
    """Record individual predictions and compute aggregate accuracy metrics.

    Metrics are stored as a running average in :class:`PMModelEvaluation` so
    that the table never grows unbounded; the ``brier_score``,
    ``accuracy``, and ``num_markets_tested`` columns are updated in-place
    on every ``record_prediction`` call.

    Args:
        db_session: Active async SQLAlchemy session.
    """

    def __init__(self, db_session: AsyncSession) -> None:
        self._db = db_session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def record_prediction(
        self,
        market_id: str,
        predicted_yes: float,
        actual_yes: float,
        model_type: str = "ensemble",
    ) -> None:
        """Update the running-average Brier score and accuracy for *model_type*.

        Uses an incremental mean formula to avoid storing individual predictions:
          new_mean = (old_mean * n + new_value) / (n + 1)

        Args:
            market_id:     Identifier for the market (used for logging only).
            predicted_yes: Model's predicted YES probability (0.0–1.0).
            actual_yes:    Observed outcome as probability (0.0 = NO, 1.0 = YES).
            model_type:    Model identifier; distinct rows per type.
        """
        brier_contribution = (predicted_yes - actual_yes) ** 2
        correct = 1.0 if (predicted_yes >= 0.5) == (actual_yes >= 0.5) else 0.0

        row = await self._get_or_create(model_type)
        n = row.num_markets_tested

        # Incremental update.
        row.brier_score = (row.brier_score * n + brier_contribution) / (n + 1)
        row.accuracy = (row.accuracy * n + correct) / (n + 1)
        row.num_markets_tested = n + 1
        row.evaluated_at = datetime.now(tz=timezone.utc)

        await self._db.flush()
        logger.debug(
            "model_evaluator: market=%s predicted=%.3f actual=%.3f brier_contribution=%.4f "
            "running_brier=%.4f n=%d",
            market_id,
            predicted_yes,
            actual_yes,
            brier_contribution,
            row.brier_score,
            row.num_markets_tested,
        )

    async def compute_brier_score(self, model_type: str = "ensemble") -> float:
        """Return the current running Brier score for *model_type*.

        Brier score = mean((predicted - actual)²).
        Lower is better; 0.25 is the score of an uninformed uniform predictor.

        Returns:
            Current Brier score, or ``0.25`` (uniform prior) if no data.
        """
        stmt = select(PMModelEvaluation).where(PMModelEvaluation.model_type == model_type)
        result = await self._db.execute(stmt)
        row: PMModelEvaluation | None = result.scalar_one_or_none()
        if row is None or row.num_markets_tested == 0:
            logger.debug("model_evaluator: no data for model_type=%s — returning 0.25", model_type)
            return 0.25
        return row.brier_score

    async def get_calibration_metrics(self, model_type: str = "ensemble") -> dict:
        """Return a summary dict of calibration metrics for *model_type*.

        Returns:
            Dict with keys ``brier_score``, ``accuracy``, ``num_markets_tested``.
            If no data exists, returns default/zero values.
        """
        stmt = select(PMModelEvaluation).where(PMModelEvaluation.model_type == model_type)
        result = await self._db.execute(stmt)
        row: PMModelEvaluation | None = result.scalar_one_or_none()
        if row is None:
            return {"brier_score": 0.25, "accuracy": 0.0, "num_markets_tested": 0}
        return {
            "brier_score": row.brier_score,
            "accuracy": row.accuracy,
            "num_markets_tested": row.num_markets_tested,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_or_create(self, model_type: str) -> PMModelEvaluation:
        """Fetch or create the :class:`PMModelEvaluation` row for *model_type*."""
        stmt = select(PMModelEvaluation).where(PMModelEvaluation.model_type == model_type)
        result = await self._db.execute(stmt)
        row: PMModelEvaluation | None = result.scalar_one_or_none()
        if row is None:
            row = PMModelEvaluation(
                model_type=model_type,
                brier_score=0.0,
                accuracy=0.0,
                num_markets_tested=0,
            )
            self._db.add(row)
            await self._db.flush()
        return row
