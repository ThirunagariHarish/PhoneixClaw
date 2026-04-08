"""Phase 15.8 Integration Smoke Tests — end-to-end pipeline wiring.

Three smoke tests exercise the full Phase 15 pipeline without any real
external calls (no live DB, no real Redis, no real LLM, no real venue HTTP).

Test coverage
-------------
test_ingest_then_embed_then_score
    Mock venue → run HistoricalIngestPipeline → run EmbeddingStore.embed_unprocessed
    → run TopBetScorer.score_batch on one market → assert confidence in 0.0–1.0.

test_agent_cycle_end_to_end
    Run one TopBetsAgent.run_cycle() with mocked venue + mocked LLM scorer.
    Assert CycleResult.error is None and top_bets_persisted >= 1.

test_api_top_bets_endpoint_returns_data
    Use FastAPI TestClient.  Override the DB session dependency to return a
    pre-populated FakeSession.  Call GET /api/v2/pm/top-bets → assert 200.

Notes
-----
- ``asyncio_mode = "auto"`` is set project-wide (pyproject.toml).
- PYTHONPATH must include the repo root: ``PYTHONPATH=. pytest ...``.
- No PostgreSQL / Redis / LLM API keys required.
"""

from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers / fakes shared across tests
# ---------------------------------------------------------------------------

_MOCK_MARKET = {
    "market_id": "rh-smoke-001",
    "venue": "robinhood_predictions",
    "question": "Will the S&P 500 close above 5000 by end of Q2 2025?",
    "yes_price": 0.55,
    "volume_usd": 80_000.0,
    "days_to_resolution": 60.0,
    "category": "finance",
    "description": "Prediction market on S&P 500 performance.",
}


def _make_fake_llm_result(yes_prob: float = 0.65, confidence: float = 0.72) -> MagicMock:
    """Build a minimal mock LLMScorerResult."""
    ref = MagicMock()
    ref.reference_class_name = "finance"
    ref.base_rate_yes = 0.52
    ref.confidence = 0.68

    cot = MagicMock()
    cot.samples = [0.63, 0.65, 0.67]
    cot.std_dev = 0.02
    cot.mean_yes_prob = 0.65

    debate = MagicMock()
    debate.bull_argument = "Strong macro tailwinds support yes."
    debate.bear_argument = "Elevated rates could cap upside."
    debate.judge_reasoning = "Balance of evidence slightly favours yes."
    debate.final_yes_prob = yes_prob
    debate.confidence_adjustment = 0.03

    result = MagicMock()
    result.yes_probability = yes_prob
    result.no_probability = 1.0 - yes_prob
    result.confidence = confidence
    result.reference_class_result = ref
    result.cot_result = cot
    result.debate_result = debate
    result.final_reasoning = "Smoke-test reasoning."
    return result


def _make_db_session_mock() -> AsyncMock:
    """Return an async mock that satisfies TopBetsAgent._persist_top_bets."""
    db = AsyncMock()
    # scalar_one_or_none → simulate market NOT found in pm_markets (fallback UUID path)
    scalar_result = AsyncMock()
    scalar_result.scalar_one_or_none = MagicMock(return_value=None)
    db.execute = AsyncMock(return_value=scalar_result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    # context manager support: `async with session_factory() as db`
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=db)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return session_factory


# ===========================================================================
# Test 1 — ingest → embed → score
# ===========================================================================


async def test_ingest_then_embed_then_score() -> None:
    """Mock venue → ingest → embed → score → confidence in valid range."""
    from agents.polymarket.data.embedding_store import EmbeddingStore
    from agents.polymarket.data.historical_ingest import HistoricalIngestPipeline
    from agents.polymarket.top_bets.scorer import ScoredMarket, TopBetScorer

    # --- Stage 1: ingest ---
    mock_venue = MagicMock()
    mock_venue.fetch_historical = AsyncMock(
        return_value=[
            {
                "id": "rh-hist-001",
                "question": "Test historical market?",
                "category": "finance",
                "winning_outcome": "yes",
                "resolution_date": "2024-12-31",
                "total_volume": 50_000.0,
                "closed_at": "2024-12-31T00:00:00Z",
            }
        ]
    )

    db_session = AsyncMock()
    # Simulate scalar_one_or_none returning None (no existing row)
    exec_result = AsyncMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=None)
    db_session.execute = AsyncMock(return_value=exec_result)
    db_session.add = MagicMock()
    db_session.flush = AsyncMock()
    db_session.commit = AsyncMock()

    pipeline = HistoricalIngestPipeline(venue=mock_venue, db_session=db_session)

    with patch("agents.polymarket.data.historical_ingest.get_venue", return_value=mock_venue):
        result = await pipeline.run()

    assert result.total_fetched >= 0  # pipeline ran without raising

    # --- Stage 2: embed_unprocessed (no real OpenAI key → 0 rows processed) ---
    embed_store = EmbeddingStore(db_session=db_session)
    # Patch the DB query so embed_unprocessed sees no pending rows
    exec_result_empty = AsyncMock()
    exec_result_empty.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    db_session.execute = AsyncMock(return_value=exec_result_empty)

    embedded = await embed_store.embed_unprocessed(batch_size=5)
    assert embedded == 0  # no rows to embed in this mock session

    # --- Stage 3: score one market with mocked LLM ---
    fake_llm_result = _make_fake_llm_result(yes_prob=0.65, confidence=0.72)
    mock_llm_scorer = MagicMock()
    mock_llm_scorer.score_market = AsyncMock(return_value=fake_llm_result)

    scorer = TopBetScorer(db_session=db_session, llm_client=MagicMock())
    # Patch the internal LLM scorer so we don't make real API calls
    scorer._llm_scorer = mock_llm_scorer

    scored_markets: list[ScoredMarket] = await scorer.score_batch([_MOCK_MARKET], top_k=1)

    # The pipeline should return at least one result
    assert len(scored_markets) >= 1, "scorer returned no markets"
    sm = scored_markets[0]
    assert 0.0 <= sm.llm_result.confidence <= 1.0, (
        f"confidence {sm.llm_result.confidence} outside [0, 1]"
    )
    assert 0.0 <= sm.llm_result.yes_probability <= 1.0


# ===========================================================================
# Test 2 — agent cycle end-to-end
# ===========================================================================


async def test_agent_cycle_end_to_end() -> None:
    """One TopBetsAgent cycle with mocked venue + LLM → CycleResult valid."""
    from agents.polymarket.top_bets.agent import CycleResult, TopBetsAgent
    from agents.polymarket.top_bets.scorer import ScoredMarket

    session_factory = _make_db_session_mock()

    # Build the agent (no real Redis needed — we patch the redis client out)
    agent = TopBetsAgent(
        db_session_factory=session_factory,
        redis_url="redis://localhost:6379",
        llm_client=None,
        venue_name="robinhood_predictions",
    )

    # Patch Redis so agent doesn't try to connect
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock()
    mock_redis.xadd = AsyncMock()
    mock_redis.aclose = AsyncMock()
    agent._redis = mock_redis

    # Build a fake ScoredMarket that passes the confidence filter (>= 0.55)
    fake_llm_result = _make_fake_llm_result(yes_prob=0.65, confidence=0.78)
    fake_sm = ScoredMarket(
        market=_MOCK_MARKET,
        heuristic_score=0.70,
        llm_result=fake_llm_result,
        final_score=0.68,
    )

    with (
        patch.object(agent, "_fetch_markets", AsyncMock(return_value=[_MOCK_MARKET])),
        patch.object(agent, "_score_and_filter", AsyncMock(return_value=[fake_sm])),
        patch.object(agent, "_persist_top_bets", AsyncMock(return_value=1)),
        patch.object(agent, "_publish_to_stream", AsyncMock(return_value=None)),
        patch.object(agent, "_update_heartbeat", AsyncMock(return_value=None)),
        patch.object(agent, "_log_activity", AsyncMock(return_value=None)),
    ):
        result: CycleResult = await agent.run_cycle()

    assert result.error is None, f"CycleResult.error should be None, got: {result.error}"
    assert result.top_bets_persisted >= 1, (
        f"Expected top_bets_persisted >= 1, got {result.top_bets_persisted}"
    )
    assert result.markets_fetched == 1
    assert result.markets_scored == 1
    assert result.cycle_duration_ms >= 0


# ===========================================================================
# Test 3 — API endpoint returns data
# ===========================================================================


class _FakeResult:
    """Minimal async-scalars result stub."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._rows[0] if self._rows else 0


class _FakeSession:
    def __init__(self, store: dict[type, list[Any]]) -> None:
        self.store = store

    async def execute(self, stmt: Any) -> _FakeResult:
        from sqlalchemy.sql import Select

        if isinstance(stmt, Select):
            entities: list[type] = []
            try:
                desc = stmt.column_descriptions or []
                for d in desc:
                    e = d.get("entity")
                    if isinstance(e, type):
                        entities.append(e)
            except Exception:
                entities = []

            if not entities:
                return _FakeResult([0])

            cls = entities[0]
            return _FakeResult(list(self.store.get(cls, [])))

        return _FakeResult([])

    def add(self, obj: Any) -> None:
        self.store.setdefault(type(obj), []).append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


def _make_top_bet_row(**kw: Any) -> Any:
    now = datetime.now(timezone.utc)
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "market_id": uuid.uuid4(),
        "venue": "robinhood_predictions",
        "recommendation_date": now.date(),
        "side": "YES",
        "confidence_score": 78,
        "edge_bps": 1300,
        "reasoning": "Smoke-test bet reasoning.",
        "status": "pending",
        "rejected_reason": None,
        "accepted_order_id": None,
        "bull_argument": "Strong bull case.",
        "bear_argument": "Moderate bear case.",
        "debate_summary": None,
        "bull_score": 70,
        "bear_score": 30,
        "sample_probabilities": [0.65, 0.66, 0.64],
        "consensus_spread": 0.02,
        "reference_class": "finance",
        "base_rate_yes": 0.52,
        "base_rate_sample_size": 30,
        "base_rate_confidence": 0.75,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(kw)
    obj = types.SimpleNamespace(**defaults)
    # Attach market relationship stub (router uses bet.market.question)
    obj.market = types.SimpleNamespace(
        question="Will the S&P 500 close above 5000 by end of Q2?",
        venue_market_id="rh-smoke-001",
    )
    return obj


def test_api_top_bets_endpoint_returns_data() -> None:
    """GET /api/v2/pm/top-bets returns HTTP 200 with pre-seeded fake rows."""
    from fastapi.testclient import TestClient
    from jose import jwt

    from apps.api.src.config import auth_settings
    from apps.api.src.main import app
    from shared.db.engine import get_session
    from shared.db.models.polymarket import PMTopBet

    # Build a FakeSession pre-seeded with one PMTopBet row
    store: dict[type, list[Any]] = {PMTopBet: [_make_top_bet_row()]}
    fake_session = _FakeSession(store)

    async def _override():
        yield fake_session

    app.dependency_overrides[get_session] = _override

    token = jwt.encode(
        {"sub": "smoke-user", "type": "access", "admin": False, "role": "user"},
        auth_settings.jwt_secret_key,
        algorithm=auth_settings.jwt_algorithm,
    )
    headers = {"Authorization": f"Bearer {token}"}

    try:
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v2/pm/top-bets", headers=headers)
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. Body: {resp.text[:500]}"
        )
        data = resp.json()
        assert isinstance(data, list), f"Expected list response, got: {type(data)}"
    finally:
        app.dependency_overrides.pop(get_session, None)
