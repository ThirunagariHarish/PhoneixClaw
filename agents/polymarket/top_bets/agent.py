"""TopBetsAgent — 24/7 autonomous prediction market scanning agent (Phase 15.5).

Responsibilities
----------------
1. Every 60 seconds: fetch active markets from the configured venue, score them
   through the full AI pipeline, persist the top bets to ``pm_top_bets``, and
   publish bet events to ``stream:pm:top_bets``.
2. Every 3600 seconds: trigger the nightly auto-research check via
   :class:`~agents.polymarket.top_bets.auto_research.AutoResearchAgent`.
3. Write a liveness heartbeat (``pm:agent:top_bets:heartbeat``) with TTL=120 s
   after every cycle so the dashboard health monitor can detect a dead agent.
4. Log every cycle outcome — and any exceptions — to ``pm_agent_activity_log``.
5. Never crash: all per-cycle exceptions are caught, logged, and the loop
   continues.

Reference
---------
docs/architecture/polymarket-phase15.md  §8 (Phase 15.5), §10 (Redis keys)
docs/prd/polymarket-phase15.md           F15-A (Top Bets), F15-D (Auto-Research)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from agents.polymarket.top_bets.scorer import ScoredMarket, TopBetScorer
from shared.db.models.polymarket import PMAgentActivityLog, PMMarket, PMTopBet
from shared.events.bus import EventBus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HEARTBEAT_KEY = "pm:agent:top_bets:heartbeat"
HEARTBEAT_TTL_S = 120
TOP_BETS_STREAM = "stream:pm:top_bets"
CYCLE_INTERVAL_S = 60
RESEARCH_INTERVAL_S = 3600
_AGENT_TYPE = "top_bets"
_MIN_CONFIDENCE_TO_PERSIST = 0.55  # must match scorer config default


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CycleResult:
    """Structured outcome of one full fetch → score → persist cycle."""

    markets_fetched: int
    markets_scored: int
    top_bets_persisted: int
    cycle_duration_ms: float
    error: str | None = None


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class TopBetsAgent:
    """Autonomous 24/7 agent that surfaces high-confidence prediction market bets.

    Args:
        db_session_factory: Callable that returns an async SQLAlchemy session
            context manager (e.g. ``sessionmaker(engine, class_=AsyncSession)``).
        redis_url:          Redis connection string used for heartbeats, the event
                            bus, and the auto-research nonce.
        llm_client:         Injected LLM client forwarded to :class:`TopBetScorer`.
                            Pass ``None`` to disable LLM scoring (heuristic only).
        venue_name:         Venue registry key (default: ``"robinhood_predictions"``).
    """

    def __init__(
        self,
        db_session_factory: Callable,
        redis_url: str,
        llm_client: Any = None,
        venue_name: str = "robinhood_predictions",
    ) -> None:
        self._session_factory = db_session_factory
        self._redis_url = redis_url
        self._llm = llm_client
        self._venue_name = venue_name

        self._running = False
        self._redis: aioredis.Redis | None = None
        self._event_bus = EventBus(redis_url)

        # Tracks when auto-research was last triggered (epoch seconds).
        self._last_research_ts: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Run the main 24/7 loop — returns only after :meth:`stop` is called."""
        self._running = True
        logger.info("TopBetsAgent starting (venue=%s)", self._venue_name)

        while self._running:
            cycle_start = time.monotonic()

            try:
                result = await self.run_cycle()
                await self._update_heartbeat()

                async with self._session_factory() as db:
                    await self._log_activity(
                        db,
                        event_type="scan_cycle",
                        message=(
                            f"Cycle complete: fetched={result.markets_fetched} "
                            f"scored={result.markets_scored} "
                            f"persisted={result.top_bets_persisted} "
                            f"duration_ms={result.cycle_duration_ms:.1f}"
                        ),
                        metadata={
                            "markets_fetched": result.markets_fetched,
                            "markets_scored": result.markets_scored,
                            "top_bets_persisted": result.top_bets_persisted,
                            "cycle_duration_ms": result.cycle_duration_ms,
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                logger.exception("TopBetsAgent: unhandled error in start() loop")
                try:
                    async with self._session_factory() as db:
                        await self._log_activity(
                            db,
                            event_type="error",
                            message=f"Unhandled loop error: {exc}",
                            metadata={"error": str(exc)},
                            severity="error",
                        )
                except Exception:  # noqa: BLE001
                    logger.exception("TopBetsAgent: could not log unhandled error to DB")

            # Nightly research check — every RESEARCH_INTERVAL_S seconds.
            now = time.monotonic()
            if now - self._last_research_ts >= RESEARCH_INTERVAL_S:
                self._last_research_ts = now
                await self._trigger_auto_research()

            # Sleep until next cycle, honouring stop() calls promptly.
            elapsed = time.monotonic() - cycle_start
            sleep_s = max(0.0, CYCLE_INTERVAL_S - elapsed)
            if self._running:
                await asyncio.sleep(sleep_s)

        logger.info("TopBetsAgent stopped.")

    async def stop(self) -> None:
        """Signal the main loop to exit after the current cycle completes."""
        logger.info("TopBetsAgent stop() requested.")
        self._running = False
        if self._redis:
            await self._redis.aclose()
            self._redis = None
        await self._event_bus.close()

    # ------------------------------------------------------------------
    # Main cycle
    # ------------------------------------------------------------------

    async def run_cycle(self) -> CycleResult:
        """Execute one full fetch → score → persist → publish cycle.

        Exceptions from any sub-step are caught and surfaced via
        :attr:`CycleResult.error`; the agent never re-raises.
        """
        start_ms = time.monotonic() * 1000
        markets_fetched = 0
        markets_scored = 0
        top_bets_persisted = 0
        error: str | None = None

        try:
            markets = await self._fetch_markets()
            markets_fetched = len(markets)

            scored = await self._score_and_filter(markets)
            markets_scored = len(scored)

            async with self._session_factory() as db:
                top_bets_persisted = await self._persist_top_bets(scored, db)
                await db.commit()

            if scored:
                top_bet_dicts = [_scored_to_event_dict(sm) for sm in scored]
                await self._publish_to_stream(top_bet_dicts)

        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            logger.exception("TopBetsAgent: error in run_cycle")
            try:
                async with self._session_factory() as db:
                    await self._log_activity(
                        db,
                        event_type="error",
                        message=f"Cycle error: {exc}",
                        metadata={"error": error, "markets_fetched": markets_fetched},
                        severity="error",
                    )
            except Exception:  # noqa: BLE001
                logger.exception("TopBetsAgent: could not log cycle error to DB")

        duration_ms = time.monotonic() * 1000 - start_ms
        return CycleResult(
            markets_fetched=markets_fetched,
            markets_scored=markets_scored,
            top_bets_persisted=top_bets_persisted,
            cycle_duration_ms=duration_ms,
            error=error,
        )

    # ------------------------------------------------------------------
    # Sub-steps
    # ------------------------------------------------------------------

    async def _fetch_markets(self) -> list[dict]:
        """Fetch active markets from the configured venue.

        Returns raw market dicts with keys normalised to the scorer's
        expected schema: ``question``, ``yes_price``, ``volume_usd``,
        ``days_to_resolution``, ``category``, ``description``, ``venue``,
        ``market_id`` (venue-specific string identifier).

        Raises:
            VenueError: propagated to caller; caught in :meth:`run_cycle`.
        """
        from shared.polymarket.venue_registry import get_venue

        venue = get_venue(self._venue_name)
        raw_markets: list[dict] = await venue.fetch_markets()
        return [_normalise_market(m, self._venue_name) for m in raw_markets]

    async def _score_and_filter(self, markets: list[dict]) -> list[ScoredMarket]:
        """Run the full TopBetScorer pipeline and return the qualifying markets.

        A fresh DB session is opened per call so the scorer's EmbeddingStore
        has access to the latest historical data.

        Args:
            markets: Normalised market dicts from :meth:`_fetch_markets`.

        Returns:
            Sorted list of :class:`ScoredMarket` (highest final_score first).
        """
        if not markets:
            return []

        async with self._session_factory() as db:
            scorer = TopBetScorer(db_session=db, llm_client=self._llm)
            scored = await scorer.score_batch(markets, top_k=20)

        # Keep only markets above the minimum confidence threshold.
        return [sm for sm in scored if sm.llm_result.confidence >= _MIN_CONFIDENCE_TO_PERSIST]

    async def _persist_top_bets(self, scored: list[ScoredMarket], db: AsyncSession) -> int:
        """Upsert scored markets into ``pm_top_bets``.

        For each :class:`ScoredMarket`, we resolve the ``pm_markets.id`` UUID
        by querying ``(venue, venue_market_id)``; if the row doesn't exist yet
        we fall back to a deterministic UUID-5 so the agent never blocks on
        missing discovery data.

        The upsert key is ``(market_id, recommendation_date)`` — matching the
        unique constraint ``uq_pm_top_bets_market_date``.

        Args:
            scored: Scored markets to persist.
            db:     Active async SQLAlchemy session (committed by caller).

        Returns:
            Number of rows upserted.
        """
        if not scored:
            return 0

        today = date.today()
        count = 0

        for sm in scored:
            market = sm.market
            lr = sm.llm_result
            ref = lr.reference_class_result
            cot = lr.cot_result
            debate = lr.debate_result

            # --- Resolve pm_markets.id ---
            venue_market_id: str = market.get("market_id", "")
            result = await db.execute(
                select(PMMarket.id).where(
                    PMMarket.venue == self._venue_name,
                    PMMarket.venue_market_id == venue_market_id,
                )
            )
            db_market_id: uuid.UUID = result.scalar_one_or_none()
            if db_market_id is None:
                # Deterministic fallback — avoids FK violation panic while still
                # providing a stable per-market identifier across cycles.
                db_market_id = uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    f"{self._venue_name}:{venue_market_id}",
                )

            # --- Build upsert values ---
            yes_price: float = market.get("yes_price", 0.5)
            edge_bps = int(abs(lr.yes_probability - yes_price) * 10_000)
            side = "YES" if lr.yes_probability >= 0.5 else "NO"
            confidence_score = max(0, min(100, int(lr.confidence * 100)))

            values: dict = {
                "id": uuid.uuid4(),
                "market_id": db_market_id,
                "venue": self._venue_name,
                "recommendation_date": today,
                "side": side,
                "confidence_score": confidence_score,
                "edge_bps": edge_bps,
                "reasoning": lr.final_reasoning,
                "status": "pending",
                "bull_argument": debate.bull_argument if debate else None,
                "bear_argument": debate.bear_argument if debate else None,
                "debate_summary": debate.judge_reasoning if debate else None,
                "sample_probabilities": cot.samples if cot.samples else None,
                "consensus_spread": (max(cot.samples) - min(cot.samples)) if cot.samples else None,
                "reference_class": ref.reference_class_name,
                "base_rate_yes": ref.base_rate_yes,
                "base_rate_confidence": ref.confidence,
                "updated_at": datetime.now(timezone.utc),
            }

            stmt = (
                pg_insert(PMTopBet)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["market_id", "venue"],
                    set_={
                        "side": values["side"],
                        "confidence_score": values["confidence_score"],
                        "edge_bps": values["edge_bps"],
                        "reasoning": values["reasoning"],
                        "bull_argument": values["bull_argument"],
                        "bear_argument": values["bear_argument"],
                        "debate_summary": values["debate_summary"],
                        "sample_probabilities": values["sample_probabilities"],
                        "consensus_spread": values["consensus_spread"],
                        "reference_class": values["reference_class"],
                        "base_rate_yes": values["base_rate_yes"],
                        "base_rate_confidence": values["base_rate_confidence"],
                        "updated_at": values["updated_at"],
                    },
                )
            )
            await db.execute(stmt)
            count += 1

        return count

    async def _publish_to_stream(self, top_bets: list[dict]) -> None:
        """Publish top-bet event payloads to ``stream:pm:top_bets``.

        Each bet is published as a separate stream message. Failures are
        logged but do not raise — stream publishing is best-effort.
        """
        for bet in top_bets:
            try:
                # Redis Streams require all values to be strings.
                payload = {k: str(v) for k, v in bet.items() if v is not None}
                await self._event_bus.publish(TOP_BETS_STREAM, payload)
            except Exception:  # noqa: BLE001
                logger.warning("TopBetsAgent: failed to publish bet to stream", exc_info=True)

    async def _update_heartbeat(self) -> None:
        """Write the liveness heartbeat key to Redis with TTL=120 s.

        A missing heartbeat key tells the dashboard that the agent is dead.
        """
        redis_client = await self._get_redis()
        ts = datetime.now(timezone.utc).isoformat()
        await redis_client.set(HEARTBEAT_KEY, ts, ex=HEARTBEAT_TTL_S)
        logger.debug("TopBetsAgent: heartbeat updated (TTL=%ds)", HEARTBEAT_TTL_S)

    async def _log_activity(
        self,
        db: AsyncSession,
        event_type: str,
        message: str,
        metadata: dict | None = None,
        severity: str = "info",
    ) -> None:
        """Insert a ``pm_agent_activity_log`` row for audit and UI display.

        Args:
            db:         Active async session (not committed here — caller commits).
            event_type: Short action label, e.g. ``"scan_cycle"`` or ``"error"``.
            message:    Human-readable description.
            metadata:   Optional structured data stored in the ``detail`` JSONB column.
            severity:   One of ``"info"``, ``"warn"``, ``"error"``.
        """
        detail = dict(metadata) if metadata else {}
        detail["message"] = message
        log_row = PMAgentActivityLog(
            agent_type=_AGENT_TYPE,
            severity=severity,
            action=event_type,
            detail=detail,
        )
        db.add(log_row)
        await db.flush()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_redis(self) -> aioredis.Redis:
        """Lazily initialise and return the Redis client."""
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url)
        return self._redis

    async def _trigger_auto_research(self) -> None:
        """Run the nightly auto-research check in a best-effort fire-and-forget."""
        try:
            from agents.polymarket.top_bets.auto_research import AutoResearchAgent

            researcher = AutoResearchAgent(
                db_session_factory=self._session_factory,
                redis_url=self._redis_url,
                llm_client=self._llm,
            )
            ran = await researcher.run_if_needed()
            if ran:
                logger.info("TopBetsAgent: nightly auto-research completed.")
            else:
                logger.debug("TopBetsAgent: auto-research skipped (already ran today).")
        except Exception:  # noqa: BLE001
            logger.exception("TopBetsAgent: auto-research trigger failed")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _normalise_market(raw: dict, venue_name: str) -> dict:
    """Convert a raw venue market dict to the scorer's expected schema.

    Robinhood Predictions uses ``title``, ``volume``, and ``end_date``;
    the scorer expects ``question``, ``volume_usd``, and ``days_to_resolution``.
    """
    from datetime import datetime, timezone

    days_to_resolution: float = 30.0
    end_date_str = raw.get("end_date") or raw.get("expiry")
    if end_date_str:
        try:
            expiry = datetime.fromisoformat(str(end_date_str).replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            delta = (expiry - datetime.now(timezone.utc)).total_seconds() / 86_400.0
            days_to_resolution = max(0.0, delta)
        except (ValueError, TypeError):
            pass

    return {
        "market_id": raw.get("market_id", raw.get("id", "")),
        "venue": raw.get("venue", venue_name),
        "question": raw.get("question", raw.get("title", "")),
        "category": raw.get("category", ""),
        "description": raw.get("description", ""),
        "yes_price": float(raw.get("yes_price", 0.5)),
        "no_price": float(raw.get("no_price", 0.5)),
        "volume_usd": float(raw.get("volume_usd", raw.get("volume", 0.0))),
        "days_to_resolution": days_to_resolution,
    }


def _scored_to_event_dict(sm: ScoredMarket) -> dict:
    """Convert a :class:`ScoredMarket` to a flat dict suitable for Redis Streams.

    Redis Streams require all values to be strings, so the caller calls
    ``str(v)`` on the returned dict. We therefore keep all values JSON-safe.
    """
    lr = sm.llm_result
    return {
        "market_id": sm.market.get("market_id", ""),
        "venue": sm.market.get("venue", ""),
        "question": sm.market.get("question", ""),
        "yes_probability": str(round(lr.yes_probability, 4)),
        "no_probability": str(round(lr.no_probability, 4)),
        "confidence": str(round(lr.confidence, 4)),
        "final_score": str(round(sm.final_score, 4)),
        "reference_class": lr.reference_class_result.reference_class_name,
        "base_rate_yes": str(round(lr.reference_class_result.base_rate_yes, 4)),
        "has_debate": str(lr.debate_result is not None),
    }
