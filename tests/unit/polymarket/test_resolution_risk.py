"""Unit tests for the F9 ResolutionRiskScorer (Phase 5).

We use a mock LLM client (no Ollama in CI) and exercise three golden cases
plus the persistence path with an in-memory stub session. PG-typed columns
on `pm_resolution_scores` (UUID, JSONB) prevent us from binding the real
ORM to SQLite, so persistence is verified through a fake session that
captures the row attributes.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from shared.polymarket.resolution_risk import (
    LLM_FALLBACK_AMBIGUITY,
    MODEL_VERSION,
    TRADEABLE_THRESHOLD,
    MarketInput,
    ResolutionRiskScorer,
    _expiry_risk,
    _oracle_risk,
    _parse_llm_json,
)


@dataclass
class FakeResp:
    text: str
    done: bool = True
    model: str = "mock"


class FakeLLM:
    """Minimal stand-in for `OllamaClient` capturing one call at a time."""

    def __init__(self, ambiguity: float | None = 0.1, rationale: str = "clean", *,
                 raise_exc: BaseException | None = None, raw_text: str | None = None,
                 done: bool = True) -> None:
        self.ambiguity = ambiguity
        self.rationale = rationale
        self.raise_exc = raise_exc
        self.raw_text = raw_text
        self.done = done
        self.calls: list[dict] = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc is not None:
            raise self.raise_exc
        if self.raw_text is not None:
            return FakeResp(text=self.raw_text, done=self.done)
        payload = {"ambiguity": self.ambiguity, "rationale": self.rationale}
        return FakeResp(text=json.dumps(payload), done=self.done)


def _now() -> datetime:
    return datetime(2026, 4, 7, tzinfo=timezone.utc)


def _scorer(llm: FakeLLM) -> ResolutionRiskScorer:
    return ResolutionRiskScorer(llm_client=llm, now_fn=_now)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def test_oracle_risk_known_and_unknown():
    assert _oracle_risk("uma") < _oracle_risk("centralized")
    assert _oracle_risk("UMA") == _oracle_risk("uma")
    assert _oracle_risk(None) > 0.5
    assert _oracle_risk("nonsense") > 0.5


def test_expiry_risk_buckets():
    now = _now()
    assert _expiry_risk(None, now=now) == 0.5
    assert _expiry_risk(now - timedelta(hours=1), now=now) == 1.0
    assert _expiry_risk(now + timedelta(hours=2), now=now) == 0.6
    assert _expiry_risk(now + timedelta(days=3), now=now) == 0.2
    assert _expiry_risk(now + timedelta(days=30), now=now) == 0.1
    assert _expiry_risk(now + timedelta(days=365), now=now) == 0.4


def test_parse_llm_json_strict():
    amb, r = _parse_llm_json('{"ambiguity": 0.3, "rationale": "ok"}')
    assert amb == 0.3 and r == "ok"


def test_parse_llm_json_embedded_in_prose():
    text = 'sure!\n{"ambiguity":0.7,"rationale":"ambig"}\nthanks'
    amb, r = _parse_llm_json(text)
    assert amb == 0.7 and r == "ambig"


def test_parse_llm_json_clamps():
    amb, _ = _parse_llm_json('{"ambiguity": 1.7, "rationale": "x"}')
    assert amb == 1.0
    amb, _ = _parse_llm_json('{"ambiguity": -0.4, "rationale": "x"}')
    assert amb == 0.0


def test_parse_llm_json_garbage():
    assert _parse_llm_json("not json at all") == (None, None)
    assert _parse_llm_json("") == (None, None)


# ---------------------------------------------------------------------------
# Golden cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_clean_uma_market_is_tradeable():
    """UMA oracle, no disputes, comfortable expiry, unambiguous wording."""
    llm = FakeLLM(ambiguity=0.05, rationale="single objective answer")
    scorer = _scorer(llm)
    market = MarketInput(
        market_id=uuid.uuid4(),
        question="Will BTC close above $100,000 on 2026-12-31 per Coinbase?",
        oracle_type="uma",
        resolution_source="coinbase",
        expiry=_now() + timedelta(days=30),
        prior_disputes=0,
    )
    result = await scorer.score(market)

    assert result.tradeable is True
    assert result.final_score < TRADEABLE_THRESHOLD
    assert result.factors.dispute_risk == 0.0
    assert result.factors.llm_ambiguity_score == 0.05
    assert result.model_version == MODEL_VERSION
    assert llm.calls and llm.calls[0]["json_mode"] is True


@pytest.mark.asyncio
async def test_disputed_market_is_blocked():
    """Multiple prior disputes alone push us across the gate."""
    llm = FakeLLM(ambiguity=0.1, rationale="clear question")
    scorer = _scorer(llm)
    market = MarketInput(
        market_id=uuid.uuid4(),
        question="Did Team X win the championship on date Y?",
        oracle_type="uma",
        resolution_source="official_league",
        expiry=_now() + timedelta(days=10),
        prior_disputes=3,
    )
    result = await scorer.score(market)

    assert result.tradeable is False
    assert result.final_score >= TRADEABLE_THRESHOLD
    assert result.factors.dispute_risk == 1.0


@pytest.mark.asyncio
async def test_ambiguous_wording_blocks_even_clean_oracle():
    llm = FakeLLM(ambiguity=0.95, rationale="vague subjective wording")
    scorer = _scorer(llm)
    market = MarketInput(
        market_id=uuid.uuid4(),
        question="Will the year be remembered as a good one for AI?",
        oracle_type="uma",
        resolution_source="vibes",
        expiry=_now() + timedelta(days=60),
        prior_disputes=0,
    )
    result = await scorer.score(market)

    assert result.tradeable is False
    assert result.factors.llm_ambiguity_score == 0.95


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_neutral_prior():
    llm = FakeLLM(raise_exc=RuntimeError("ollama down"))
    scorer = _scorer(llm)
    market = MarketInput(
        market_id=uuid.uuid4(),
        question="Will it rain tomorrow in NYC per NWS?",
        oracle_type="uma",
        resolution_source="nws",
        expiry=_now() + timedelta(days=1),
        prior_disputes=0,
    )
    result = await scorer.score(market)
    assert result.factors.llm_ambiguity_score == LLM_FALLBACK_AMBIGUITY
    assert "llm_unavailable" in result.factors.llm_rationale


@pytest.mark.asyncio
async def test_llm_returns_unparseable_text_uses_fallback():
    llm = FakeLLM(raw_text="lol I'm a chatbot, not JSON")
    scorer = _scorer(llm)
    market = MarketInput(
        market_id=uuid.uuid4(),
        question="Will X happen by Y per Z?",
        oracle_type="uma",
        resolution_source="z",
        expiry=_now() + timedelta(days=14),
        prior_disputes=0,
    )
    result = await scorer.score(market)
    assert result.factors.llm_ambiguity_score == LLM_FALLBACK_AMBIGUITY


@pytest.mark.asyncio
async def test_centralized_oracle_lifts_score():
    llm_clean = FakeLLM(ambiguity=0.05)
    base = MarketInput(
        market_id=uuid.uuid4(),
        question="Will the centralized resolver call this Yes?",
        oracle_type="uma",
        resolution_source="x",
        expiry=_now() + timedelta(days=30),
        prior_disputes=0,
    )
    a = await _scorer(llm_clean).score(base)

    llm_clean2 = FakeLLM(ambiguity=0.05)
    centralized = MarketInput(
        market_id=base.market_id,
        question=base.question,
        oracle_type="centralized",
        resolution_source="x",
        expiry=base.expiry,
        prior_disputes=0,
    )
    b = await _scorer(llm_clean2).score(centralized)
    assert b.final_score > a.final_score


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class FakeSession:
    def __init__(self) -> None:
        self.added: list = []
        self.flushed = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        self.flushed += 1


@pytest.mark.asyncio
async def test_score_and_persist_writes_row():
    llm = FakeLLM(ambiguity=0.1, rationale="clean")
    scorer = _scorer(llm)
    session = FakeSession()
    market = MarketInput(
        market_id=uuid.uuid4(),
        question="Will ETH close above $5000 on 2026-12-31 per Coinbase?",
        oracle_type="uma",
        resolution_source="coinbase",
        expiry=_now() + timedelta(days=20),
        prior_disputes=0,
    )

    result = await scorer.score_and_persist(market, session)  # type: ignore[arg-type]
    assert session.flushed == 1
    assert len(session.added) == 1
    row = session.added[0]
    assert row.pm_market_id == market.market_id
    assert row.tradeable is result.tradeable
    assert row.final_score == result.final_score
    assert row.llm_ambiguity_score == 0.1
    assert row.llm_rationale == "clean"
    assert row.model_version == MODEL_VERSION


@pytest.mark.asyncio
async def test_score_and_persist_requires_market_id():
    scorer = _scorer(FakeLLM())
    market = MarketInput(
        market_id=None,
        question="q",
        oracle_type="uma",
        resolution_source=None,
        expiry=None,
        prior_disputes=0,
    )
    with pytest.raises(ValueError):
        await scorer.score_and_persist(market, FakeSession())  # type: ignore[arg-type]
