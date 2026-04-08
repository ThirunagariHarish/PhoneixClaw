"""Unit tests for Phase 15.3 — HistoricalIngestPipeline and EmbeddingStore.

All tests use mock / fake DB sessions to avoid PostgreSQL-specific type
incompatibilities (UUID, JSONB) with SQLite.  No network access; the venue
and any embedding API calls are intercepted via unittest.mock.

asyncio_mode = "auto" (set in pyproject.toml) — no @pytest.mark.asyncio needed.
"""

from __future__ import annotations

import math
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.polymarket.data.embedding_store import (
    _EMBED_DIM,
    _HASH_MODEL_ID,
    EmbeddingStore,
    SimilarMarket,
)
from agents.polymarket.data.historical_ingest import HistoricalIngestPipeline, IngestResult

# ---------------------------------------------------------------------------
# Helpers — fake venue markets
# ---------------------------------------------------------------------------


def _make_market(suffix: str = "001") -> dict[str, Any]:
    return {
        "market_id": f"rh-test-{suffix}",
        "title": f"Will test event {suffix} happen?",
        "category": "test",
        "yes_price": 0.45,
        "no_price": 0.55,
        "volume": 10_000,
        "end_date": "2025-12-31",
        "description": f"Test market {suffix}",
        "venue": "robinhood",
    }


# ---------------------------------------------------------------------------
# Helpers — fake ORM objects
# ---------------------------------------------------------------------------


def _make_historical_market(
    market_id: uuid.UUID | None = None,
    venue_market_id: str = "rh-test-001",
    question: str = "Will test event happen?",
    reference_class: str | None = "test",
    winning_outcome: str | None = None,
) -> MagicMock:
    """Return a MagicMock that looks like a PMHistoricalMarket row."""
    m = MagicMock()
    m.id = market_id or uuid.uuid4()
    m.venue_market_id = venue_market_id
    m.question = question
    m.reference_class = reference_class
    m.winning_outcome = winning_outcome
    return m


def _make_embedding_row(historical_market_id: uuid.UUID, vector: list[float]) -> MagicMock:
    """Return a MagicMock that looks like a PMMarketEmbedding row."""
    e = MagicMock()
    e.id = uuid.uuid4()
    e.historical_market_id = historical_market_id
    e.embedding = vector
    e.model_used = _HASH_MODEL_ID
    return e


# ---------------------------------------------------------------------------
# Helpers — simple fake AsyncSession builders
# ---------------------------------------------------------------------------


def _make_ingest_session() -> AsyncMock:
    """Session for ingest tests: tracks add() calls.

    execute() is not relied on here because we patch _market_already_exists
    on the pipeline directly to keep tests simple and focused.
    """
    session = AsyncMock()
    session._added: list[Any] = []
    # add() is synchronous in SQLAlchemy (fire-and-forget to the unit-of-work)
    session.add = MagicMock(side_effect=lambda obj: session._added.append(obj))
    session.flush = AsyncMock(return_value=None)
    return session


def _make_embed_session(market_rows: list[Any] | None = None) -> AsyncMock:
    """Session for embed_unprocessed tests.

    Returns *market_rows* from a scalars().all() chain.
    """
    session = AsyncMock()
    session._added: list[Any] = []
    session.add = MagicMock(side_effect=lambda obj: session._added.append(obj))
    session.flush = AsyncMock(return_value=None)

    # Build a plain (non-async) result object so that .scalars().all() works
    scalars_result = MagicMock()
    scalars_result.all.return_value = market_rows or []
    sync_result = MagicMock()
    sync_result.scalars.return_value = scalars_result
    session.execute = AsyncMock(return_value=sync_result)
    return session


def _make_find_session(embedding_pairs: list[tuple[Any, Any]] | None = None) -> AsyncMock:
    """Session for find_similar tests.  Returns *embedding_pairs* from .all()."""
    session = AsyncMock()
    sync_result = MagicMock()
    sync_result.all.return_value = embedding_pairs or []
    session.execute = AsyncMock(return_value=sync_result)
    return session


# ===========================================================================
# HistoricalIngestPipeline tests
# ===========================================================================


async def test_ingest_pipeline_stores_new_markets() -> None:
    """Venue markets that don't yet exist should be added to the session."""
    session = _make_ingest_session()

    with patch("agents.polymarket.data.historical_ingest.get_venue") as mock_get_venue:
        mock_venue = AsyncMock()
        mock_venue.fetch_markets.return_value = [_make_market("001"), _make_market("002")]
        mock_get_venue.return_value = mock_venue

        pipeline = HistoricalIngestPipeline(session)
        pipeline._market_already_exists = AsyncMock(return_value=False)

        result = await pipeline.run(max_markets=10)

    assert result.new_stored == 2
    assert result.total_fetched == 2
    assert result.skipped_duplicates == 0
    assert session.add.call_count == 2
    assert session.flush.called


async def test_ingest_pipeline_deduplicates() -> None:
    """Markets flagged as already existing should not be added a second time."""
    session = _make_ingest_session()

    with patch("agents.polymarket.data.historical_ingest.get_venue") as mock_get_venue:
        mock_venue = AsyncMock()
        mock_venue.fetch_markets.return_value = [_make_market("001")]
        mock_get_venue.return_value = mock_venue

        pipeline = HistoricalIngestPipeline(session)
        # First call: new market; second call: already exists
        pipeline._market_already_exists = AsyncMock(side_effect=[False, True])

        result1 = await pipeline.run(max_markets=10)
        result2 = await pipeline.run(max_markets=10)

    assert result1.new_stored == 1
    assert result2.new_stored == 0
    assert result2.skipped_duplicates == 1
    # add() called only once across both runs
    assert session.add.call_count == 1


async def test_ingest_returns_correct_counts() -> None:
    """IngestResult fields must reflect actual fetch / store / skip counts."""
    session = _make_ingest_session()
    markets = [_make_market(str(i).zfill(3)) for i in range(5)]

    with patch("agents.polymarket.data.historical_ingest.get_venue") as mock_get_venue:
        mock_venue = AsyncMock()
        mock_venue.fetch_markets.return_value = markets
        mock_get_venue.return_value = mock_venue

        pipeline = HistoricalIngestPipeline(session)
        # First 3 are new; last 2 are duplicates
        pipeline._market_already_exists = AsyncMock(side_effect=[False, False, False, True, True])

        result = await pipeline.run(max_markets=10)

    assert result.total_fetched == 5
    assert result.new_stored == 3
    assert result.skipped_duplicates == 2
    assert isinstance(result, IngestResult)


async def test_ingest_maps_fields_correctly() -> None:
    """ORM object field values must map correctly from the venue dict."""
    session = _make_ingest_session()
    market = _make_market("x01")

    with patch("agents.polymarket.data.historical_ingest.get_venue") as mock_get_venue:
        mock_venue = AsyncMock()
        mock_venue.fetch_markets.return_value = [market]
        mock_get_venue.return_value = mock_venue

        pipeline = HistoricalIngestPipeline(session)
        pipeline._market_already_exists = AsyncMock(return_value=False)

        await pipeline.run(max_markets=10)

    assert session.add.call_count == 1
    added_obj = session._added[0]
    assert added_obj.venue_market_id == market["market_id"]
    assert added_obj.question == market["title"]
    assert added_obj.reference_class == market["category"]
    assert added_obj.volume_usd == float(market["volume"])
    assert added_obj.outcomes_json == ["Yes", "No"]


# ===========================================================================
# EmbeddingStore tests
# ===========================================================================


async def test_embedding_store_embeds_unprocessed() -> None:
    """embed_unprocessed should create one PMMarketEmbedding per unprocessed market."""
    market_rows = [
        _make_historical_market(venue_market_id=f"rh-{i:03d}", question=f"Question {i}")
        for i in range(3)
    ]

    session = _make_embed_session(market_rows=market_rows)
    store = EmbeddingStore(session)
    count = await store.embed_unprocessed(batch_size=50)

    assert count == 3
    assert session.add.call_count == 3
    assert session.flush.called
    # Verify the added rows have required embedding attributes
    for added in session._added:
        assert hasattr(added, "embedding")
        assert hasattr(added, "historical_market_id")
        assert len(added.embedding) == _EMBED_DIM


async def test_embedding_store_uses_hash_model_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without OPENAI_API_KEY the model_used field should be the hash model id."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    market_rows = [_make_historical_market()]
    session = _make_embed_session(market_rows=market_rows)

    store = EmbeddingStore(session)
    await store.embed_unprocessed()

    added = session._added[0]
    assert added.model_used == _HASH_MODEL_ID


async def test_find_similar_returns_top_k() -> None:
    """find_similar should return at most top_k results ordered by similarity desc."""
    texts = [f"Market about topic number {i}" for i in range(5)]
    temp_store = EmbeddingStore(AsyncMock())  # used only for _hash_embed
    vectors = [temp_store._hash_embed(t) for t in texts]
    market_ids = [uuid.uuid4() for _ in range(5)]

    embedding_pairs = [
        (
            _make_embedding_row(market_ids[i], vectors[i]),
            _make_historical_market(market_id=market_ids[i], question=texts[i]),
        )
        for i in range(5)
    ]

    session = _make_find_session(embedding_pairs=embedding_pairs)
    store = EmbeddingStore(session)
    results = await store.find_similar("Market about topic number 2", top_k=3)

    assert len(results) == 3
    assert isinstance(results[0], SimilarMarket)
    # Descending similarity order
    for i in range(len(results) - 1):
        assert results[i].similarity_score >= results[i + 1].similarity_score
    # Exact match is the most similar — similarity should be 1.0
    assert results[0].similarity_score == pytest.approx(1.0, abs=1e-6)


async def test_find_similar_returns_empty_when_no_embeddings() -> None:
    """find_similar should return an empty list when the store is empty."""
    session = _make_find_session(embedding_pairs=[])
    store = EmbeddingStore(session)
    results = await store.find_similar("any query", top_k=10)
    assert results == []


# ===========================================================================
# Cosine similarity unit tests
# ===========================================================================


def test_cosine_similarity_identical_vectors() -> None:
    """Cosine similarity of a vector with itself should be exactly 1.0."""
    store = EmbeddingStore(AsyncMock())
    v = [1.0, 2.0, 3.0, 4.0]
    assert store._cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors() -> None:
    """Cosine similarity of orthogonal vectors should be 0.0."""
    store = EmbeddingStore(AsyncMock())
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert store._cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-9)


def test_cosine_similarity_opposite_vectors() -> None:
    """Cosine similarity of opposite-direction vectors should be -1.0."""
    store = EmbeddingStore(AsyncMock())
    v = [1.0, 2.0, 3.0]
    neg_v = [-1.0, -2.0, -3.0]
    assert store._cosine_similarity(v, neg_v) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector_returns_zero() -> None:
    """A zero vector should return 0.0 without raising ZeroDivisionError."""
    store = EmbeddingStore(AsyncMock())
    assert store._cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# ===========================================================================
# Hash embedding unit tests
# ===========================================================================


def test_hash_embedding_is_deterministic() -> None:
    """Same input text always produces the same vector."""
    text = "Will the Fed cut rates in 2025?"
    v1 = EmbeddingStore._hash_embed(text)
    v2 = EmbeddingStore._hash_embed(text)
    assert v1 == v2


def test_hash_embedding_different_texts_differ() -> None:
    """Different texts should produce different vectors."""
    v1 = EmbeddingStore._hash_embed("text alpha")
    v2 = EmbeddingStore._hash_embed("text beta")
    assert v1 != v2


def test_hash_embedding_is_normalized() -> None:
    """The L2 norm of the hash embedding should be approximately 1.0."""
    v = EmbeddingStore._hash_embed("normalisation check")
    norm = math.sqrt(sum(x * x for x in v))
    assert norm == pytest.approx(1.0, abs=1e-6)


def test_hash_embedding_has_correct_dimension() -> None:
    """The hash embedding should be exactly 1536-dimensional."""
    v = EmbeddingStore._hash_embed("dimension check")
    assert len(v) == _EMBED_DIM


def test_hash_embedding_empty_string() -> None:
    """An empty string should still produce a valid normalised vector."""
    v = EmbeddingStore._hash_embed("")
    assert len(v) == _EMBED_DIM
    norm = math.sqrt(sum(x * x for x in v))
    assert norm == pytest.approx(1.0, abs=1e-6)
