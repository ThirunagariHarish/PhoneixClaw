"""Reference Class Forecasting scorer for Prediction Markets (Phase 15.4).

Anchors a probability estimate on the empirical base-rate of similar,
historically-resolved markets retrieved from the embedding store.

Reference:
    docs/prd/pm-accuracy-reference-class.md  (F-ACC-3)
    docs/architecture/polymarket-phase15.md  § 9 (Scorer Chain)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select

from agents.polymarket.data.embedding_store import EmbeddingStore, SimilarMarket
from shared.db.models.polymarket import PMHistoricalMarket

logger = logging.getLogger(__name__)

# Minimum number of similar resolved markets required before we trust the
# computed base-rate.  Fewer than this falls back to a uniform 0.5 prior.
_MIN_RESOLVED_MARKETS = 3


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReferenceClassResult:
    """Output of :class:`ReferenceClassScorer`."""

    base_rate_yes: float
    """Estimated probability of YES derived from historically resolved markets (0.0–1.0)."""

    similar_markets: list[SimilarMarket]
    """Top-k similar markets returned by the embedding store."""

    confidence: float
    """How much we trust the base-rate estimate (0.0–1.0). Low when few comps exist."""

    reference_class_name: str
    """Name / category of the reference class used as a label."""


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class ReferenceClassScorer:
    """Estimate a base-rate probability using historically similar markets.

    Args:
        embedding_store: Fully initialised :class:`EmbeddingStore` instance.
            Its ``.db`` session is re-used to retrieve winning outcomes for
            the similar market IDs.
    """

    def __init__(self, embedding_store: EmbeddingStore) -> None:
        self._store = embedding_store

    async def score(self, question: str, category: str = "") -> ReferenceClassResult:
        """Compute a reference-class base-rate for *question*.

        Steps:
        1.  Retrieve up to 10 semantically similar historical markets.
        2.  Fetch their ``winning_outcome`` from the DB.
        3.  Compute base_rate = fraction where outcome == "YES".
        4.  If fewer than :data:`_MIN_RESOLVED_MARKETS` resolved comps are
            found, return a uniform prior (0.5) with very low confidence.

        Args:
            question: The prediction market question text.
            category: Optional category label used as the
                ``reference_class_name`` in the result.

        Returns:
            :class:`ReferenceClassResult` with base_rate_yes and confidence.
        """
        similar: list[SimilarMarket] = await self._store.find_similar(question, top_k=10)

        if not similar:
            logger.debug("reference_class: no similar markets found for '%s'", question[:80])
            return ReferenceClassResult(
                base_rate_yes=0.5,
                similar_markets=[],
                confidence=0.1,
                reference_class_name=category or "unknown",
            )

        # Fetch winning outcomes for the returned market IDs via the shared DB session.
        market_ids: list[uuid.UUID] = [m.market_id for m in similar]
        stmt = select(PMHistoricalMarket.id, PMHistoricalMarket.winning_outcome).where(
            PMHistoricalMarket.id.in_(market_ids)
        )
        result = await self._store.db.execute(stmt)
        rows: dict[uuid.UUID, str | None] = {row[0]: row[1] for row in result.all()}

        # Compute YES base-rate only from resolved (winning_outcome known) markets.
        yes_flags: list[float] = []
        for m in similar:
            outcome = rows.get(m.market_id)
            if outcome is None:
                continue  # unresolved — skip
            yes_flags.append(1.0 if outcome.upper() == "YES" else 0.0)

        resolved_count = len(yes_flags)
        if resolved_count < _MIN_RESOLVED_MARKETS:
            logger.debug(
                "reference_class: only %d resolved comps (<3), using uniform prior",
                resolved_count,
            )
            return ReferenceClassResult(
                base_rate_yes=0.5,
                similar_markets=similar,
                confidence=0.1,
                reference_class_name=category or "unknown",
            )

        base_rate = sum(yes_flags) / resolved_count
        # Confidence scales with sample size, capped at 1.0.
        # At 10 resolved markets → confidence ~0.9; at 3 → ~0.4.
        confidence = min(1.0, resolved_count / 11.0)

        logger.debug(
            "reference_class: base_rate=%.3f from %d resolved comps (category=%s)",
            base_rate,
            resolved_count,
            category or "unknown",
        )
        return ReferenceClassResult(
            base_rate_yes=base_rate,
            similar_markets=similar,
            confidence=confidence,
            reference_class_name=category or "unknown",
        )
