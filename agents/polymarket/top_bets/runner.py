"""runner.py — standalone entry-point for TopBetsAgent (Phase 15.5).

Usage (from repo root)::

    PYTHONPATH=. python agents/polymarket/top_bets/runner.py

Or via Makefile / Docker:

    make run-top-bets-agent

Environment variables
---------------------
DATABASE_URL   Async SQLAlchemy URL (postgresql+asyncpg://...)
REDIS_URL      Redis connection string (redis://localhost:6379)
VENUE_NAME     Venue registry key (default: robinhood_predictions)
LLM_MODEL      LLM model name forwarded to the OpenClaw LLM client
"""

from __future__ import annotations

import asyncio
import logging
import os

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger(__name__)


def _build_session_factory():
    """Construct a SQLAlchemy async session factory from ``DATABASE_URL``."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader")
    engine = create_async_engine(db_url, echo=False, pool_pre_ping=True)
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _build_llm_client():
    """Attempt to build an LLM client; returns ``None`` if not configured.

    The agent degrades gracefully to heuristic-only scoring when no LLM
    client is available.
    """
    try:
        # OpenClaw LLM client — available when the full stack is running.
        from shared.llm.client import LLMClient  # type: ignore[import]

        model = os.getenv("LLM_MODEL", "claude-3-5-haiku-20241022")
        return LLMClient(model=model)
    except ImportError:
        logger.warning("runner: shared.llm.client not available — running without LLM scorer")
        return None


async def main() -> None:
    """Construct and start the TopBetsAgent."""
    from agents.polymarket.top_bets.agent import TopBetsAgent

    session_factory = _build_session_factory()
    llm_client = _build_llm_client()
    venue_name = os.getenv("VENUE_NAME", "robinhood_predictions")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    agent = TopBetsAgent(
        db_session_factory=session_factory,
        redis_url=redis_url,
        llm_client=llm_client,
        venue_name=venue_name,
    )

    logger.info("runner: starting TopBetsAgent (venue=%s)", venue_name)
    try:
        await agent.start()
    except KeyboardInterrupt:
        logger.info("runner: KeyboardInterrupt — stopping agent")
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
