"""AutoResearchAgent — nightly strategy research runner (Phase 15.5).

Runs once per calendar day (UTC).  Uses a Redis nonce key
``pm:research:last_run_date`` to prevent same-day re-execution.

Workflow
--------
1. :meth:`run_if_needed` checks the Redis nonce.
2. If today's date is not set, it calls :meth:`_run_research_cycle`.
3. ``_run_research_cycle`` identifies the top-3 market categories by
   volume/confidence from recent ``pm_top_bets`` rows.
4. For each category the LLM generates 5 research query strings
   (actual web search is deferred to Phase 16).
5. Results are stored in ``pm_strategy_research_log``.
6. The nonce is written so the cycle won't re-run until tomorrow.

Reference
---------
docs/architecture/polymarket-phase15.md  §8 (Phase 15.5), §10 (Redis keys)
docs/prd/polymarket-phase15.md           F15-D (Auto-Research)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import redis.asyncio as aioredis
from sqlalchemy import func, select

from shared.db.models.polymarket import PMStrategyResearchLog, PMTopBet

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESEARCH_NONCE_KEY = "pm:research:last_run_date"
_QUERIES_PER_CATEGORY = 5
_TOP_CATEGORIES = 3
_AGENT_TYPE = "auto_research"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ResearchResult:
    """Structured outcome of one auto-research cycle."""

    categories_identified: list[str]
    queries_generated: list[str]
    timestamp: datetime


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class AutoResearchAgent:
    """Nightly strategy-improvement agent.

    Args:
        db_session_factory: Callable returning an async SQLAlchemy session
            context manager.
        redis_url:          Redis connection string.
        llm_client:         Injected LLM client for query generation.
                            Pass ``None`` to fall back to template-based queries.
    """

    def __init__(
        self,
        db_session_factory: Callable,
        redis_url: str,
        llm_client: Any = None,
    ) -> None:
        self._session_factory = db_session_factory
        self._redis_url = redis_url
        self._llm = llm_client
        self._redis: aioredis.Redis | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_if_needed(self) -> bool:
        """Run the research cycle unless it has already run today (UTC).

        Returns:
            ``True`` if research ran this call; ``False`` if it was skipped.
        """
        if await self._should_run_today() is False:
            logger.info("AutoResearchAgent: already ran today — skipping.")
            return False

        async with self._session_factory() as db:
            result = await self._run_research_cycle(db)
            await self._store_research_log(db, result)
            await db.commit()

        # Write nonce so today won't run again.
        redis_client = await self._get_redis()
        today_str = datetime.now(timezone.utc).date().isoformat()
        await redis_client.set(RESEARCH_NONCE_KEY, today_str)

        logger.info(
            "AutoResearchAgent: research cycle complete — categories=%d queries=%d",
            len(result.categories_identified),
            len(result.queries_generated),
        )
        return True

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    async def _should_run_today(self) -> bool:
        """Return ``True`` if research should run (nonce not set for today).

        Checks the ``pm:research:last_run_date`` Redis key.  If the stored
        date equals today's UTC date the cycle is skipped.
        """
        redis_client = await self._get_redis()
        stored: bytes | None = await redis_client.get(RESEARCH_NONCE_KEY)
        if stored is None:
            return True
        stored_str = stored.decode() if isinstance(stored, bytes) else stored
        today_str = datetime.now(timezone.utc).date().isoformat()
        return stored_str != today_str

    async def _run_research_cycle(self, db: Any) -> ResearchResult:
        """Execute the full research cycle within an open DB session.

        Steps:
        1. Identify hot categories from recent ``pm_top_bets``.
        2. Generate search queries per category via LLM (or template fallback).
        3. Return a :class:`ResearchResult`.

        Args:
            db: Open async SQLAlchemy session.

        Returns:
            :class:`ResearchResult` with populated categories and queries.
        """
        categories = await self._identify_hot_categories(db)
        queries = await self._generate_search_queries(categories)
        return ResearchResult(
            categories_identified=categories,
            queries_generated=queries,
            timestamp=datetime.now(timezone.utc),
        )

    async def _identify_hot_categories(self, db: Any) -> list[str]:
        """Query ``pm_top_bets`` for the top-3 categories by average confidence.

        Uses the ``reference_class`` column as the category label since it is
        populated by the scorer's Reference Class stage and is always available.
        Falls back to a default list when the table is empty.

        Args:
            db: Open async SQLAlchemy session.

        Returns:
            List of up to :data:`_TOP_CATEGORIES` category name strings.
        """
        try:
            stmt = (
                select(
                    PMTopBet.reference_class,
                    func.avg(PMTopBet.confidence_score).label("avg_confidence"),
                    func.count(PMTopBet.id).label("count"),
                )
                .where(PMTopBet.reference_class.isnot(None))
                .group_by(PMTopBet.reference_class)
                .order_by(
                    func.avg(PMTopBet.confidence_score).desc(),
                    func.count(PMTopBet.id).desc(),
                )
                .limit(_TOP_CATEGORIES)
            )
            result = await db.execute(stmt)
            rows = result.all()
            categories = [row.reference_class for row in rows if row.reference_class]
        except Exception:  # noqa: BLE001
            logger.warning("AutoResearchAgent: could not query categories — using defaults", exc_info=True)
            categories = []

        if not categories:
            categories = ["politics", "economics", "sports"]

        logger.debug("AutoResearchAgent: hot categories = %s", categories)
        return categories[:_TOP_CATEGORIES]

    async def _generate_search_queries(self, categories: list[str]) -> list[str]:
        """Generate research query strings for each category.

        When an LLM client is available it is asked to generate
        :data:`_QUERIES_PER_CATEGORY` distinct search queries per category.
        If the LLM is unavailable or raises, template-based fallback queries
        are produced so the cycle never silently produces empty results.

        Args:
            categories: Category names from :meth:`_identify_hot_categories`.

        Returns:
            Flat list of query strings (up to ``len(categories) * 5`` items).
        """
        all_queries: list[str] = []

        for category in categories:
            queries = await self._generate_queries_for_category(category)
            all_queries.extend(queries)

        return all_queries

    async def _generate_queries_for_category(self, category: str) -> list[str]:
        """Generate :data:`_QUERIES_PER_CATEGORY` query strings for *category*."""
        if self._llm is not None:
            try:
                return await self._llm_queries(category)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "AutoResearchAgent: LLM query generation failed for %r — using templates",
                    category,
                    exc_info=True,
                )

        return _template_queries(category)

    async def _llm_queries(self, category: str) -> list[str]:
        """Ask the LLM for 5 research queries for *category*.

        The LLM is expected to return a JSON array of exactly
        :data:`_QUERIES_PER_CATEGORY` strings.  If parsing fails,
        raises :exc:`ValueError` so the caller can fall back to templates.
        """
        prompt = (
            f"You are a prediction market research assistant. "
            f"Generate exactly {_QUERIES_PER_CATEGORY} distinct web search query strings "
            f"that a prediction market analyst would use to improve their forecasting "
            f"accuracy for the '{category}' category. "
            f"Return ONLY a JSON array of strings, no preamble."
        )
        response = await self._llm.generate(prompt)
        text: str = response.text if hasattr(response, "text") else str(response)

        # Strip markdown code fences if present.
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError(f"LLM returned non-list JSON: {parsed!r}")
        return [str(q) for q in parsed[:_QUERIES_PER_CATEGORY]]

    async def _store_research_log(self, db: Any, result: ResearchResult) -> None:
        """Insert a ``pm_strategy_research_log`` row for the given *result*.

        Args:
            db:     Open async SQLAlchemy session (committed by caller).
            result: The completed research result.
        """
        raw_findings = (
            f"Categories identified: {', '.join(result.categories_identified)}\n"
            f"Queries generated ({len(result.queries_generated)}):\n"
            + "\n".join(f"  - {q}" for q in result.queries_generated)
        )

        log_row = PMStrategyResearchLog(
            run_at=result.timestamp,
            sources_queried={"categories": result.categories_identified},
            raw_findings=raw_findings,
            proposed_config_delta={"queries": result.queries_generated},
        )
        db.add(log_row)
        await db.flush()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url)
        return self._redis


# ---------------------------------------------------------------------------
# Template fallback query generator (LLM-free)
# ---------------------------------------------------------------------------

_CATEGORY_TEMPLATES: dict[str, list[str]] = {
    "politics": [
        "prediction market accuracy politics US elections historical analysis",
        "political event forecasting base rates research 2024",
        "superforecaster methods political predictions site:gjopen.com",
        "conditional probability political outcomes research paper",
        "election prediction market calibration study",
    ],
    "economics": [
        "prediction market economic indicators forecasting accuracy",
        "GDP inflation interest rate prediction market calibration",
        "economic event base rates prediction markets research",
        "Federal Reserve policy prediction accuracy historical",
        "macro forecasting prediction market consensus research",
    ],
    "sports": [
        "prediction market sports outcomes base rates research",
        "sports event forecasting accuracy model comparison",
        "prediction market sports arbitrage calibration study",
        "sports betting vs prediction market pricing efficiency",
        "sports event prediction market historical resolution data",
    ],
    "crypto": [
        "crypto prediction market accuracy research study",
        "blockchain event forecasting base rates analysis",
        "cryptocurrency price prediction market calibration",
        "defi protocol event prediction market historical",
        "crypto market prediction accuracy versus implied volatility",
    ],
    "science": [
        "scientific prediction market accuracy FDA approval rates",
        "clinical trial prediction market calibration research",
        "technology milestone forecasting accuracy base rates",
        "AI prediction market research outcomes study",
        "science event forecasting superforecaster methods",
    ],
}

_DEFAULT_TEMPLATES = [
    "prediction market calibration accuracy research {category}",
    "prediction market base rates {category} historical analysis",
    "forecasting accuracy {category} events prediction markets",
    "superforecaster methods {category} prediction market study",
    "prediction market edge {category} resolution data research",
]


def _template_queries(category: str) -> list[str]:
    """Return template-based queries for *category* without an LLM call."""
    if category.lower() in _CATEGORY_TEMPLATES:
        return list(_CATEGORY_TEMPLATES[category.lower()])
    return [t.format(category=category) for t in _DEFAULT_TEMPLATES]
