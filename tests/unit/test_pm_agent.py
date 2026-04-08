"""Unit tests for TopBetsAgent and AutoResearchAgent (Phase 15.5).

All tests use mocked Redis, DB session, and LLM clients.
``asyncio_mode = "auto"`` is set project-wide so no ``@pytest.mark.asyncio``
decorator is needed.

Test coverage
-------------
- test_run_cycle_returns_cycle_result          CycleResult fields populated
- test_run_cycle_persists_top_bets             _persist_top_bets called
- test_run_cycle_handles_exception_gracefully  fetch raises → CycleResult.error set
- test_heartbeat_set_with_ttl                  Redis key written with TTL=120
- test_stream_published_after_cycle            stream:pm:top_bets published
- test_auto_research_skips_if_ran_today        nonce set → run_if_needed False
- test_auto_research_runs_if_not_ran_today     no nonce → runs + sets nonce
- test_activity_log_written_on_error           exception → PMAgentActivityLog row
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from agents.polymarket.top_bets.agent import (
    HEARTBEAT_KEY,
    HEARTBEAT_TTL_S,
    TOP_BETS_STREAM,
    CycleResult,
    TopBetsAgent,
)
from agents.polymarket.top_bets.auto_research import AutoResearchAgent, ResearchResult

# ---------------------------------------------------------------------------
# Shared fixtures and helpers
# ---------------------------------------------------------------------------


def _make_scored_market(
    market_id: str = "rh-test-001",
    yes_prob: float = 0.65,
    confidence: float = 0.80,
) -> Any:
    """Build a minimal ScoredMarket-like object with mocked internals."""
    ref = MagicMock()
    ref.reference_class_name = "politics"
    ref.base_rate_yes = 0.55
    ref.confidence = 0.70

    cot = MagicMock()
    cot.samples = [0.60, 0.65, 0.70]
    cot.std_dev = 0.05
    cot.mean_yes_prob = 0.65

    debate = MagicMock()
    debate.bull_argument = "Strong bull case"
    debate.bear_argument = "Strong bear case"
    debate.judge_reasoning = "Judge summary"
    debate.final_yes_prob = 0.65
    debate.confidence_adjustment = 0.05

    llm_result = MagicMock()
    llm_result.yes_probability = yes_prob
    llm_result.no_probability = 1.0 - yes_prob
    llm_result.confidence = confidence
    llm_result.reference_class_result = ref
    llm_result.cot_result = cot
    llm_result.debate_result = debate
    llm_result.final_reasoning = "Test reasoning text."

    sm = MagicMock()
    sm.market = {
        "market_id": market_id,
        "venue": "robinhood_predictions",
        "question": "Will X happen?",
        "yes_price": 0.50,
        "volume_usd": 50_000.0,
        "days_to_resolution": 30.0,
        "category": "politics",
        "description": "Test market description.",
    }
    sm.heuristic_score = 0.70
    sm.llm_result = llm_result
    sm.final_score = yes_prob * confidence
    return sm


def _make_db_session(market_uuid: uuid.UUID | None = None) -> AsyncMock:
    """Return an async mock DB session.

    If *market_uuid* is provided, the ``scalar_one_or_none`` result on the
    first execute call returns that UUID (simulating a pm_markets hit).
    """
    db = AsyncMock()
    scalar_result = AsyncMock()
    scalar_result.scalar_one_or_none = MagicMock(return_value=market_uuid)
    db.execute = AsyncMock(return_value=scalar_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)
    return db


def _make_session_factory(db: AsyncMock) -> MagicMock:
    """Wrap a mock DB session in a context-manager-compatible factory callable."""
    factory = MagicMock()
    factory.return_value = db
    return factory


def _make_redis_mock() -> AsyncMock:
    """Return a minimal async Redis mock."""
    r = AsyncMock()
    r.set = AsyncMock(return_value=True)
    r.get = AsyncMock(return_value=None)
    r.aclose = AsyncMock()
    return r


# ---------------------------------------------------------------------------
# test_run_cycle_returns_cycle_result
# ---------------------------------------------------------------------------


async def test_run_cycle_returns_cycle_result():
    """run_cycle() should return a populated CycleResult with no error."""
    scored = [_make_scored_market()]
    db = _make_db_session(market_uuid=uuid.uuid4())
    factory = _make_session_factory(db)

    agent = TopBetsAgent(db_session_factory=factory, redis_url="redis://localhost:6379")

    with (
        patch.object(agent, "_fetch_markets", new=AsyncMock(return_value=[{"question": "Q?"}])),
        patch.object(agent, "_score_and_filter", new=AsyncMock(return_value=scored)),
        patch.object(agent, "_persist_top_bets", new=AsyncMock(return_value=1)),
        patch.object(agent, "_publish_to_stream", new=AsyncMock()),
    ):
        result = await agent.run_cycle()

    assert isinstance(result, CycleResult)
    assert result.markets_fetched == 1
    assert result.markets_scored == 1
    assert result.top_bets_persisted == 1
    assert result.cycle_duration_ms >= 0
    assert result.error is None


# ---------------------------------------------------------------------------
# test_run_cycle_persists_top_bets
# ---------------------------------------------------------------------------


async def test_run_cycle_persists_top_bets():
    """run_cycle() must call _persist_top_bets with the scored markets."""
    scored = [_make_scored_market()]
    db = _make_db_session(market_uuid=uuid.uuid4())
    factory = _make_session_factory(db)

    persist_mock = AsyncMock(return_value=1)
    agent = TopBetsAgent(db_session_factory=factory, redis_url="redis://localhost:6379")

    with (
        patch.object(agent, "_fetch_markets", new=AsyncMock(return_value=[{}])),
        patch.object(agent, "_score_and_filter", new=AsyncMock(return_value=scored)),
        patch.object(agent, "_persist_top_bets", new=persist_mock),
        patch.object(agent, "_publish_to_stream", new=AsyncMock()),
    ):
        await agent.run_cycle()

    persist_mock.assert_awaited_once()
    call_args = persist_mock.await_args
    # First positional arg is the scored list.
    assert call_args.args[0] is scored


# ---------------------------------------------------------------------------
# test_run_cycle_handles_exception_gracefully
# ---------------------------------------------------------------------------


async def test_run_cycle_handles_exception_gracefully():
    """If _fetch_markets raises, run_cycle() must return CycleResult with error set."""
    db = _make_db_session()
    factory = _make_session_factory(db)

    agent = TopBetsAgent(db_session_factory=factory, redis_url="redis://localhost:6379")

    with patch.object(
        agent,
        "_fetch_markets",
        new=AsyncMock(side_effect=RuntimeError("venue down")),
    ):
        result = await agent.run_cycle()

    assert result.error is not None
    assert "venue down" in result.error
    assert result.markets_fetched == 0
    # Agent must not re-raise.


# ---------------------------------------------------------------------------
# test_heartbeat_set_with_ttl
# ---------------------------------------------------------------------------


async def test_heartbeat_set_with_ttl():
    """_update_heartbeat() must set the Redis key with TTL=120."""
    redis_mock = _make_redis_mock()

    db = _make_db_session()
    factory = _make_session_factory(db)
    agent = TopBetsAgent(db_session_factory=factory, redis_url="redis://localhost:6379")

    with patch.object(agent, "_get_redis", new=AsyncMock(return_value=redis_mock)):
        await agent._update_heartbeat()

    redis_mock.set.assert_awaited_once()
    call_kwargs = redis_mock.set.await_args
    # Validate key and TTL in positional / keyword args.
    assert call_kwargs.args[0] == HEARTBEAT_KEY
    assert call_kwargs.kwargs.get("ex") == HEARTBEAT_TTL_S


# ---------------------------------------------------------------------------
# test_stream_published_after_cycle
# ---------------------------------------------------------------------------


async def test_stream_published_after_cycle():
    """_publish_to_stream() must be called with non-empty data after scoring."""
    scored = [_make_scored_market()]
    db = _make_db_session(market_uuid=uuid.uuid4())
    factory = _make_session_factory(db)

    publish_mock = AsyncMock()
    agent = TopBetsAgent(db_session_factory=factory, redis_url="redis://localhost:6379")
    agent._event_bus = MagicMock()
    agent._event_bus.publish = publish_mock

    with (
        patch.object(agent, "_fetch_markets", new=AsyncMock(return_value=[{}])),
        patch.object(agent, "_score_and_filter", new=AsyncMock(return_value=scored)),
        patch.object(agent, "_persist_top_bets", new=AsyncMock(return_value=1)),
    ):
        await agent.run_cycle()

    publish_mock.assert_awaited()
    # The first publish call must target the correct stream.
    first_call_args = publish_mock.await_args_list[0]
    assert first_call_args.args[0] == TOP_BETS_STREAM


# ---------------------------------------------------------------------------
# test_auto_research_skips_if_ran_today
# ---------------------------------------------------------------------------


async def test_auto_research_skips_if_ran_today():
    """run_if_needed() must return False when the nonce equals today's date."""
    today_str = datetime.now(timezone.utc).date().isoformat().encode()

    db = _make_db_session()
    factory = _make_session_factory(db)
    redis_mock = _make_redis_mock()
    redis_mock.get = AsyncMock(return_value=today_str)

    agent = AutoResearchAgent(db_session_factory=factory, redis_url="redis://localhost:6379")

    with patch.object(agent, "_get_redis", new=AsyncMock(return_value=redis_mock)):
        result = await agent.run_if_needed()

    assert result is False


# ---------------------------------------------------------------------------
# test_auto_research_runs_if_not_ran_today
# ---------------------------------------------------------------------------


async def test_auto_research_runs_if_not_ran_today():
    """run_if_needed() must run the cycle and set the nonce when not yet run today."""
    db = _make_db_session()
    factory = _make_session_factory(db)
    redis_mock = _make_redis_mock()
    # No nonce set → should run.
    redis_mock.get = AsyncMock(return_value=None)

    agent = AutoResearchAgent(db_session_factory=factory, redis_url="redis://localhost:6379")

    fake_result = ResearchResult(
        categories_identified=["politics"],
        queries_generated=["q1", "q2"],
        timestamp=datetime.now(timezone.utc),
    )

    with (
        patch.object(agent, "_get_redis", new=AsyncMock(return_value=redis_mock)),
        patch.object(agent, "_run_research_cycle", new=AsyncMock(return_value=fake_result)),
        patch.object(agent, "_store_research_log", new=AsyncMock()),
    ):
        result = await agent.run_if_needed()

    assert result is True
    # Nonce must have been written.
    redis_mock.set.assert_awaited_once()
    nonce_call = redis_mock.set.await_args
    today_str = datetime.now(timezone.utc).date().isoformat()
    assert nonce_call.args[1] == today_str


# ---------------------------------------------------------------------------
# test_activity_log_written_on_error
# ---------------------------------------------------------------------------


async def test_activity_log_written_on_error():
    """When _fetch_markets raises, a PMAgentActivityLog row must be added to the DB."""
    db = _make_db_session()
    factory = _make_session_factory(db)

    agent = TopBetsAgent(db_session_factory=factory, redis_url="redis://localhost:6379")

    with patch.object(
        agent,
        "_fetch_markets",
        new=AsyncMock(side_effect=ValueError("mock failure")),
    ):
        result = await agent.run_cycle()

    # Error is surfaced in CycleResult.
    assert result.error is not None

    # db.add must have been called (PMAgentActivityLog row).
    db.add.assert_called()

    # Verify the added object has the expected PMAgentActivityLog attributes.
    # Use class-name check to avoid isinstance() brittleness under global mocking.
    added_objs = [call.args[0] for call in db.add.call_args_list]
    log_rows = [o for o in added_objs if type(o).__name__ == "PMAgentActivityLog"]
    assert len(log_rows) >= 1
    assert log_rows[0].severity == "error"
    assert log_rows[0].agent_type == "top_bets"


# ---------------------------------------------------------------------------
# test_start_loop_continues_after_cycle_exception
# ---------------------------------------------------------------------------


async def test_start_loop_continues_after_cycle_exception():
    """Verify that start() loop does not propagate exceptions from run_cycle()."""
    call_count = 0

    db = _make_db_session()
    factory = _make_session_factory(db)

    agent = TopBetsAgent(db_session_factory=factory, redis_url="redis://localhost:6379")

    async def flaky_cycle():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated cycle failure")
        # On second call, stop the agent so the test terminates.
        agent._running = False
        return CycleResult(
            markets_fetched=0,
            markets_scored=0,
            top_bets_persisted=0,
            cycle_duration_ms=0.0,
            error=None,
        )

    with (
        patch.object(agent, "run_cycle", new=flaky_cycle),
        patch.object(agent, "_update_heartbeat", new=AsyncMock()),
        patch.object(agent, "_trigger_auto_research", new=AsyncMock()),
        patch("asyncio.sleep", new=AsyncMock()),
    ):
        # start() must NOT raise — it catches the exception and continues.
        await agent.start()

    assert call_count == 2  # iterated twice — did not crash on first exception
