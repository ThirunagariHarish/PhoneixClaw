"""Unit tests for the Phase 15.4 Scorer Chain.

All LLM and DB calls are mocked — no real API calls are made.

asyncio_mode = "auto" is set in pyproject.toml, so no @pytest.mark.asyncio needed.

NOTE: The production models in shared/db/models/ and several shared/* modules
target Python 3.11+ (union type syntax in SQLAlchemy Mapped[] annotations and
dataclass fields).  The test runner uses Python 3.9.  We pre-stub the affected
modules in sys.modules *before* importing any production code so the ORM mapper
and any 3.10+ syntax never runs.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Python 3.9 compat: pre-stub shared.db and agents.polymarket.data chain
# ---------------------------------------------------------------------------
# The repository targets Python 3.11+ but the test runner may use Python 3.9.
# SQLAlchemy evaluates Mapped[X | None] at mapper-config time via eval(); that
# fails on 3.9.  agents.polymarket.data.__init__ also pulls in shared.polymarket
# which pulls in shared.llm.client (dataclass with X | None field) — same issue.
#
# Strategy:
#   1. Stub all shared.db.models.* with MagicMock (avoiding ORM init).
#   2. Stub agents.polymarket.data package with MagicMock (avoiding __init__).
#   3. Load agents.polymarket.data.embedding_store DIRECTLY via importlib
#      (bypassing the package __init__) so the real EmbeddingStore / SimilarMarket
#      classes are available for type-correct mocking.


class _FakePMModelEvaluation:
    """Minimal plain-Python fake for PMModelEvaluation (no SQLAlchemy)."""

    # Class-level descriptors: needed so production code can do PMModelEvaluation.model_type
    # as a column reference in SQLAlchemy select/where statements (which we patch in tests).
    model_type = MagicMock()

    def __init__(
        self,
        *,
        model_type: str = "ensemble",
        brier_score: float = 0.0,
        accuracy: float = 0.0,
        num_markets_tested: int = 0,
        is_active: bool = False,
        evaluated_at: object = None,
        **_kw: object,
    ) -> None:
        self.model_type = model_type  # instance attribute shadows class-level mock
        self.brier_score = brier_score
        self.accuracy = accuracy
        self.num_markets_tested = num_markets_tested
        self.is_active = is_active
        self.evaluated_at = evaluated_at


class _FakePMHistoricalMarket:
    """Minimal plain-Python fake for PMHistoricalMarket (no SQLAlchemy)."""

    # Class-level descriptors so PMHistoricalMarket.id and .winning_outcome work
    # as arguments to (patched) select() calls.
    id = MagicMock()
    winning_outcome = MagicMock()

    def __init__(
        self,
        *,
        id: uuid.UUID | None = None,
        winning_outcome: str | None = None,
        **_kw: object,
    ) -> None:
        self.id = id or uuid.uuid4()  # instance attribute shadows class-level mock
        self.winning_outcome = winning_outcome


# Build polymarket stub module with the fake classes.
_pm_stub = MagicMock()
_pm_stub.PMModelEvaluation = _FakePMModelEvaluation
_pm_stub.PMHistoricalMarket = _FakePMHistoricalMarket
_pm_stub.PMMarketEmbedding = MagicMock()
_pm_stub.PMTopBet = MagicMock()
_pm_stub.PMMarket = MagicMock()
_pm_stub.PMStrategy = MagicMock()
_pm_stub.PMOrder = MagicMock()

# Inject shared.db stubs BEFORE any project imports.
for _mod_name in [
    "shared.db",
    "shared.db.engine",
    "shared.db.models",
    "shared.db.models.base",
    "shared.db.models.agent",
    "shared.db.models.agent_chat",
    "shared.db.models.agent_message",
    "shared.db.models.agent_metric",
    "shared.db.models.agent_session",
    "shared.db.models.agent_trade",
    "shared.db.models.api_key",
    "shared.db.models.audit_log",
    "shared.db.models.backtest_trade",
    "shared.db.models.connector",
    "shared.db.models.dev_incident",
    "shared.db.models.error_log",
    "shared.db.models.learning_session",
    "shared.db.models.notification",
    "shared.db.models.skill",
    "shared.db.models.strategy",
    "shared.db.models.system_log",
    "shared.db.models.task",
    "shared.db.models.token_usage",
    "shared.db.models.trade",
    "shared.db.models.trade_signal",
    "shared.db.models.trading_account",
    "shared.db.models.user",
    "shared.db.models.watchlist",
]:
    sys.modules.setdefault(_mod_name, MagicMock())
sys.modules["shared.db.models.polymarket"] = _pm_stub

# Stub agents.polymarket.data PACKAGE so __init__.py doesn't run.
sys.modules.setdefault("agents.polymarket.data", MagicMock())

# Load embedding_store directly, bypassing the package __init__ chain.
_ES_PATH = str(
    __import__("pathlib").Path(__file__).parents[2]
    / "agents"
    / "polymarket"
    / "data"
    / "embedding_store.py"
)
_es_spec = importlib.util.spec_from_file_location("agents.polymarket.data.embedding_store", _ES_PATH)
_es_module = importlib.util.module_from_spec(_es_spec)
sys.modules["agents.polymarket.data.embedding_store"] = _es_module
_es_spec.loader.exec_module(_es_module)  # type: ignore[union-attr]

# ---------------------------------------------------------------------------
# Helpers / shared fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeGenerateResponse:
    """Mimics shared.llm.client.GenerateResponse."""

    text: str
    model: str = "test-model"
    done: bool = True


def _make_llm_client(*responses: str) -> MagicMock:
    """Return a mock LLM client whose .generate() cycles through *responses*."""
    client = MagicMock()
    call_results = [FakeGenerateResponse(text=t) for t in responses]
    # If only one response supplied, repeat it indefinitely.
    if len(call_results) == 1:
        client.generate = AsyncMock(return_value=call_results[0])
    else:
        client.generate = AsyncMock(side_effect=call_results)
    return client


def _make_embedding_store(similar_markets=None, winning_outcomes=None) -> MagicMock:
    """Return a mock EmbeddingStore.

    Args:
        similar_markets: List of SimilarMarket-like objects returned by find_similar.
        winning_outcomes: dict mapping UUID → str ("YES"/"NO") returned by db queries.
    """
    store = MagicMock()
    store.find_similar = AsyncMock(return_value=similar_markets or [])

    # Mock the DB session's execute / result chain.
    db_mock = AsyncMock()
    winning_outcomes = winning_outcomes or {}
    # Build fake rows list: list of (uuid, outcome) tuples.
    rows = list(winning_outcomes.items())

    result_mock = MagicMock()
    result_mock.all.return_value = rows
    db_mock.execute = AsyncMock(return_value=result_mock)
    store.db = db_mock
    return store


def _similar_market(market_id=None, question="Test?", similarity=0.9, ref_class="politics") -> object:
    from agents.polymarket.data.embedding_store import SimilarMarket

    return SimilarMarket(
        market_id=market_id or uuid.uuid4(),
        question_text=question,
        similarity_score=similarity,
        reference_class=ref_class,
    )


# ---------------------------------------------------------------------------
# ReferenceClassScorer tests
# ---------------------------------------------------------------------------


class TestReferenceClassScorer:
    async def test_reference_class_uniform_prior_when_few_similar(self):
        """Fewer than 3 resolved comps → base_rate=0.5, confidence=0.1."""
        from agents.polymarket.top_bets.reference_class import ReferenceClassScorer

        # Only 2 similar markets, both with winning_outcomes.
        ids = [uuid.uuid4(), uuid.uuid4()]
        similar = [_similar_market(market_id=ids[0]), _similar_market(market_id=ids[1])]
        store = _make_embedding_store(
            similar_markets=similar,
            winning_outcomes={ids[0]: "YES", ids[1]: "NO"},
        )
        scorer = ReferenceClassScorer(store)
        with patch("agents.polymarket.top_bets.reference_class.select", return_value=MagicMock()):
            result = await scorer.score("Will X happen?", category="politics")

        assert result.base_rate_yes == 0.5
        assert result.confidence == pytest.approx(0.1)
        assert result.reference_class_name == "politics"

    async def test_reference_class_computes_base_rate_correctly(self):
        """4 YES out of 5 resolved → base_rate ≈ 0.8."""
        from agents.polymarket.top_bets.reference_class import ReferenceClassScorer

        ids = [uuid.uuid4() for _ in range(5)]
        similar = [_similar_market(market_id=i) for i in ids]
        outcomes = {ids[0]: "YES", ids[1]: "YES", ids[2]: "YES", ids[3]: "YES", ids[4]: "NO"}
        store = _make_embedding_store(similar_markets=similar, winning_outcomes=outcomes)
        scorer = ReferenceClassScorer(store)
        with patch("agents.polymarket.top_bets.reference_class.select", return_value=MagicMock()):
            result = await scorer.score("Will X happen?", category="crypto")

        assert result.base_rate_yes == pytest.approx(0.8)
        assert result.confidence > 0.1
        assert result.reference_class_name == "crypto"

    async def test_reference_class_no_similar_markets(self):
        """Empty find_similar → uniform prior (no DB query needed)."""
        from agents.polymarket.top_bets.reference_class import ReferenceClassScorer

        store = _make_embedding_store(similar_markets=[], winning_outcomes={})
        scorer = ReferenceClassScorer(store)
        result = await scorer.score("Novel question?")

        assert result.base_rate_yes == 0.5
        assert result.confidence == pytest.approx(0.1)

    async def test_reference_class_ignores_unresolved_markets(self):
        """Markets with None winning_outcome are excluded from base_rate calc."""
        from agents.polymarket.top_bets.reference_class import ReferenceClassScorer

        ids = [uuid.uuid4() for _ in range(5)]
        similar = [_similar_market(market_id=i) for i in ids]
        # Only 3 have outcomes (2 are unresolved / missing from DB result).
        outcomes = {ids[0]: "YES", ids[1]: "NO", ids[2]: "YES"}
        store = _make_embedding_store(similar_markets=similar, winning_outcomes=outcomes)
        scorer = ReferenceClassScorer(store)
        with patch("agents.polymarket.top_bets.reference_class.select", return_value=MagicMock()):
            result = await scorer.score("Will Y happen?", category="sports")

        # 2 YES out of 3 resolved → 0.667
        assert result.base_rate_yes == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# CoTSampler tests
# ---------------------------------------------------------------------------


class TestCoTSampler:
    async def test_cot_sampler_trims_outliers(self):
        """With 5 samples, min and max are dropped before computing mean."""
        from agents.polymarket.top_bets.cot_sampler import CoTSampler

        # Samples: 0.1, 0.4, 0.5, 0.6, 0.9 → trimmed: 0.4, 0.5, 0.6 → mean = 0.5
        responses = ["step... 0.1", "step... 0.4", "step... 0.5", "step... 0.6", "step... 0.9"]
        client = _make_llm_client(*responses)
        sampler = CoTSampler(client, config={})
        result = await sampler.sample("Will X happen?", context="some context", n=5)

        assert result.mean_yes_prob == pytest.approx(0.5, abs=1e-6)
        assert len(result.samples) == 5
        assert len(result.reasoning_traces) == 5

    async def test_cot_sampler_parallel_calls(self):
        """Verify asyncio.gather is used: all N calls happen concurrently."""
        from agents.polymarket.top_bets.cot_sampler import CoTSampler

        call_order: list[int] = []
        call_count = 0

        async def fake_generate(prompt, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            call_order.append(idx)
            return FakeGenerateResponse(text=f"probability is 0.{idx + 5}")

        client = MagicMock()
        client.generate = fake_generate

        sampler = CoTSampler(client, config={})
        result = await sampler.sample("Will X happen?", context="ctx", n=5)

        # All 5 calls were made.
        assert call_count == 5
        assert len(result.samples) == 5

    async def test_cot_graceful_degradation(self):
        """All LLM calls fail → mean=0.5, std_dev=0.5, empty samples."""
        from agents.polymarket.top_bets.cot_sampler import CoTSampler

        client = MagicMock()
        client.generate = AsyncMock(side_effect=RuntimeError("LLM down"))

        sampler = CoTSampler(client, config={})
        result = await sampler.sample("Will X happen?", context="ctx", n=5)

        assert result.mean_yes_prob == pytest.approx(0.5)
        assert result.std_dev == pytest.approx(0.5)
        assert result.samples == []
        assert result.reasoning_traces == []

    async def test_cot_sampler_partial_failure_above_threshold(self):
        """3 out of 5 succeed → still returns valid result (not degradation)."""
        from agents.polymarket.top_bets.cot_sampler import CoTSampler

        responses_and_errors = [
            FakeGenerateResponse(text="prob 0.6"),
            RuntimeError("fail"),
            FakeGenerateResponse(text="prob 0.7"),
            FakeGenerateResponse(text="prob 0.5"),
            RuntimeError("fail"),
        ]
        client = MagicMock()
        client.generate = AsyncMock(side_effect=responses_and_errors)

        sampler = CoTSampler(client, config={})
        result = await sampler.sample("Will X?", context="ctx", n=5)

        # 3 successes: should NOT degrade; samples list is populated.
        assert len(result.samples) == 3
        assert 0.0 <= result.mean_yes_prob <= 1.0

    async def test_cot_sampler_uses_config_model(self):
        """The config llm.model and temperature are forwarded to generate()."""
        from agents.polymarket.top_bets.cot_sampler import CoTSampler

        client = _make_llm_client("answer is 0.7")
        cfg = {"llm": {"model": "test-model-42", "temperature": 0.1, "max_tokens": 512}}
        sampler = CoTSampler(client, config=cfg)
        await sampler.sample("Q?", context="ctx", n=1)

        call_kwargs = client.generate.call_args[1]
        assert call_kwargs.get("model") == "test-model-42"
        assert call_kwargs.get("temperature") == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# DebateScorer tests
# ---------------------------------------------------------------------------


class TestDebateScorer:
    async def test_debate_scorer_three_sequential_calls(self):
        """Exactly 3 LLM calls in order: Bull → Bear → Judge."""
        from agents.polymarket.top_bets.debate_scorer import DebateScorer

        call_log: list[str] = []

        async def fake_generate(prompt, **kwargs):
            # Use unique identifiers from each prompt template in debate_scorer.py
            if "confident investment analyst" in prompt:
                call_log.append("bull")
                return FakeGenerateResponse(text="Strong YES because A, B, C.")
            elif "skeptical investment analyst" in prompt:
                call_log.append("bear")
                return FakeGenerateResponse(text="Strong NO because X, Y, Z.")
            else:
                call_log.append("judge")
                return FakeGenerateResponse(text="After weighing both sides: 0.6")

        client = MagicMock()
        client.generate = fake_generate

        scorer = DebateScorer(client, config={})
        result = await scorer.score("Will it rain?", context="weather data", cot_estimate=0.5)

        # Three rounds fired in order: bull, bear, judge.
        assert len(call_log) == 3
        assert call_log[0] == "bull"
        assert call_log[1] == "bear"
        assert call_log[2] == "judge"
        # The judge float was parsed correctly.
        assert result.final_yes_prob == pytest.approx(0.6)

    async def test_debate_scorer_confidence_adjustment(self):
        """confidence_adjustment = final_yes_prob - cot_estimate."""
        from agents.polymarket.top_bets.debate_scorer import DebateScorer

        # Judge returns 0.7; cot_estimate = 0.5 → adjustment = +0.2
        client = _make_llm_client(
            "Bull argument here.",
            "Bear argument here.",
            "Judge says the probability is 0.7",
        )
        scorer = DebateScorer(client, config={})
        result = await scorer.score("Question?", context="ctx", cot_estimate=0.5)

        assert result.final_yes_prob == pytest.approx(0.7)
        assert result.confidence_adjustment == pytest.approx(0.2, abs=1e-6)

    async def test_debate_scorer_fallback_on_unparseable_judge(self):
        """If judge response has no float, final_yes_prob falls back to cot_estimate."""
        from agents.polymarket.top_bets.debate_scorer import DebateScorer

        client = _make_llm_client("Bull.", "Bear.", "I cannot decide.")
        scorer = DebateScorer(client, config={})
        result = await scorer.score("Q?", context="ctx", cot_estimate=0.42)

        assert result.final_yes_prob == pytest.approx(0.42)
        assert result.confidence_adjustment == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# LLMScorer tests
# ---------------------------------------------------------------------------


class TestLLMScorer:
    def _make_scorer(self, cot_responses=None, ref_base_rate=0.4, n_similar=5):
        """Helper to build an LLMScorer with mocked sub-components."""
        from agents.polymarket.top_bets.llm_scorer import LLMScorer

        ids = [uuid.uuid4() for _ in range(n_similar)]
        similar = [_similar_market(market_id=i) for i in ids]
        outcomes = {i: ("YES" if idx < round(n_similar * ref_base_rate) else "NO") for idx, i in enumerate(ids)}
        store = _make_embedding_store(similar_markets=similar, winning_outcomes=outcomes)

        if cot_responses is None:
            cot_responses = ["0.6"] * 5
        client = _make_llm_client(*cot_responses)
        cfg = {
            "scorer": {"reference_class_weight": 0.3, "llm_weight": 0.5, "cot_samples": 5},
            "llm": {"temperature": 0.3, "max_tokens": 512},
        }
        return LLMScorer(store, client, cfg)

    async def test_llm_scorer_blends_weights_correctly(self):
        """Fixed inputs → verify blended output matches manual calculation."""
        from agents.polymarket.top_bets.llm_scorer import _blend

        # ref_rate=0.4, cot_mean=0.6, no debate.
        # ref_weight=0.3, llm_weight=0.5 → total=0.8, blend = (0.3*0.4 + 0.5*0.6) / 0.8
        # = (0.12 + 0.30) / 0.8 = 0.42 / 0.8 = 0.525
        expected = (0.3 * 0.4 + 0.5 * 0.6) / (0.3 + 0.5)
        result = _blend(ref_rate=0.4, cot_mean=0.6, debate_result=None, ref_weight=0.3, llm_weight=0.5)
        assert result == pytest.approx(expected, abs=1e-6)

    async def test_llm_scorer_with_debate_blends_three_way(self):
        """When debate is present, blend uses ref + half_cot + half_debate."""
        from agents.polymarket.top_bets.debate_scorer import DebateResult
        from agents.polymarket.top_bets.llm_scorer import _blend

        debate = DebateResult(
            final_yes_prob=0.8,
            bull_argument="",
            bear_argument="",
            judge_reasoning="",
            confidence_adjustment=0.2,
        )
        # ref=0.3 weight, remaining=0.7 split evenly → cot=0.35, debate=0.35
        result = _blend(ref_rate=0.4, cot_mean=0.6, debate_result=debate, ref_weight=0.3, llm_weight=0.5)
        expected = 0.3 * 0.4 + 0.35 * 0.6 + 0.35 * 0.8
        assert result == pytest.approx(expected, abs=1e-6)

    async def test_llm_scorer_score_market_no_debate(self):
        """End-to-end: score_market with run_debate=False completes without error."""
        from agents.polymarket.top_bets.reference_class import ReferenceClassResult

        scorer = self._make_scorer(cot_responses=["0.5", "0.6", "0.7", "0.6", "0.5"])
        fake_ref = ReferenceClassResult(
            base_rate_yes=0.4, similar_markets=[], confidence=0.5, reference_class_name="test"
        )
        with patch.object(scorer._ref_scorer, "score", AsyncMock(return_value=fake_ref)):
            result = await scorer.score_market(
                {"question": "Will X happen?", "category": "politics", "yes_price": 0.5},
                run_debate=False,
            )
        assert 0.0 <= result.yes_probability <= 1.0
        assert result.no_probability == pytest.approx(1.0 - result.yes_probability)
        assert result.debate_result is None
        assert result.cot_result is not None
        assert result.reference_class_result is not None

    async def test_llm_scorer_confidence_equals_one_minus_std(self):
        """confidence = 1 - cot_result.std_dev."""
        from agents.polymarket.top_bets.reference_class import ReferenceClassResult

        scorer = self._make_scorer(cot_responses=["0.5", "0.5", "0.5", "0.5", "0.5"])
        fake_ref = ReferenceClassResult(
            base_rate_yes=0.5, similar_markets=[], confidence=0.5, reference_class_name="test"
        )
        with patch.object(scorer._ref_scorer, "score", AsyncMock(return_value=fake_ref)):
            result = await scorer.score_market({"question": "Q?"}, run_debate=False)
        # All samples identical → std_dev ≈ 0 → confidence ≈ 1.0
        assert result.confidence == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# TopBetScorer tests
# ---------------------------------------------------------------------------


class TestTopBetScorer:
    def _make_top_bet_scorer(self, n_markets=20, cot_response="0.6"):
        """Build a TopBetScorer with a mocked DB session and LLM client."""
        from agents.polymarket.top_bets.scorer import TopBetScorer

        db = AsyncMock()
        # Fake the DB execute → empty results so EmbeddingStore returns no similar markets.
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        result_mock.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)
        db.flush = AsyncMock()
        db.add = MagicMock()

        client = _make_llm_client(cot_response)

        # Patch EmbeddingStore.find_similar to return empty (no similar markets).
        with patch(
            "agents.polymarket.top_bets.scorer.EmbeddingStore",
            autospec=True,
        ) as mock_store_cls:
            mock_store_instance = mock_store_cls.return_value
            mock_store_instance.find_similar = AsyncMock(return_value=[])
            mock_store_instance.db = db
            scorer = TopBetScorer(db_session=db, llm_client=client, config_path=None)
            scorer._embedding_store = mock_store_instance
            scorer._llm_scorer._embedding_store = mock_store_instance
            scorer._llm_scorer._ref_scorer._store = mock_store_instance

        return scorer

    async def test_top_bet_scorer_runs_debate_only_top5(self):
        """With 20 input markets, debate is called for exactly 5 markets."""
        from agents.polymarket.top_bets.cot_sampler import CoTResult
        from agents.polymarket.top_bets.llm_scorer import LLMScorerResult
        from agents.polymarket.top_bets.reference_class import ReferenceClassResult
        from agents.polymarket.top_bets.scorer import TopBetScorer

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.all.return_value = []
        db.execute = AsyncMock(return_value=result_mock)
        db.flush = AsyncMock()
        db.add = MagicMock()

        client = _make_llm_client("0.6")

        markets = [
            {
                "question": f"Will market {i} resolve YES?",
                "volume_usd": 10_000 * (i + 1),
                "yes_price": 0.5,
                "days_to_resolution": 30,
            }
            for i in range(20)
        ]

        debate_call_count = 0

        def make_fake_llm_result(yes_prob=0.6) -> LLMScorerResult:
            return LLMScorerResult(
                yes_probability=yes_prob,
                no_probability=1 - yes_prob,
                confidence=0.8,
                reference_class_result=ReferenceClassResult(
                    base_rate_yes=0.5, similar_markets=[], confidence=0.1, reference_class_name="test"
                ),
                cot_result=CoTResult(
                    mean_yes_prob=yes_prob, std_dev=0.1, samples=[yes_prob] * 5, reasoning_traces=["t"] * 5
                ),
                debate_result=None,
                final_reasoning="test",
            )

        async def fake_score_market(market, run_debate=False):
            nonlocal debate_call_count
            if run_debate:
                debate_call_count += 1
            return make_fake_llm_result()

        with patch("agents.polymarket.top_bets.scorer.EmbeddingStore"):
            scorer = TopBetScorer(db_session=db, llm_client=client, config_path=None)
            scorer._llm_scorer.score_market = fake_score_market

            results = await scorer.score_batch(markets, top_k=20)

        assert debate_call_count == 5, f"Expected 5 debate calls, got {debate_call_count}"
        assert len(results) <= 20

    async def test_heuristic_score_prefers_liquid_near_50pct(self):
        """High volume + yes_price≈0.5 + 30 days → heuristic score near top."""
        from agents.polymarket.top_bets.scorer import (
            _liquidity_score,
            _price_centrality_score,
            _time_horizon_score,
        )

        high_volume = _liquidity_score(1_000_000)  # $1M → ~0.857
        good_days = _time_horizon_score(30)  # in sweet spot → 1.0
        central_price = _price_centrality_score(0.5)  # exactly 0.5 → 1.0
        score = (high_volume + good_days + central_price) / 3.0

        assert score > 0.7, f"Expected high score, got {score:.3f}"

        # Compare against a bad market: very low volume, price near 1.0.
        low_volume = _liquidity_score(10)
        extreme_price = _price_centrality_score(0.95)
        bad_score = (low_volume + good_days + extreme_price) / 3.0

        assert score > bad_score

    async def test_heuristic_time_horizon_penalty(self):
        """Days outside 7-60 range receive score penalty."""
        from agents.polymarket.top_bets.scorer import _time_horizon_score

        assert _time_horizon_score(3) < _time_horizon_score(30)  # too short
        assert _time_horizon_score(200) == 0.0  # too long (>180)
        assert _time_horizon_score(30) == pytest.approx(1.0)  # ideal
        assert _time_horizon_score(60) == pytest.approx(1.0)  # upper edge
        assert _time_horizon_score(0.5) == 0.0  # below 1 day

    async def test_heuristic_score_components_range(self):
        """All heuristic sub-scores must be in [0, 1]."""
        from agents.polymarket.top_bets.scorer import (
            _liquidity_score,
            _price_centrality_score,
            _time_horizon_score,
        )

        for vol in [0, 1, 100, 10_000, 1_000_000, 100_000_000]:
            s = _liquidity_score(vol)
            assert 0.0 <= s <= 1.0, f"liquidity_score({vol}) = {s}"

        for days in [0, 1, 7, 30, 60, 90, 180, 365]:
            s = _time_horizon_score(days)
            assert 0.0 <= s <= 1.0, f"time_horizon_score({days}) = {s}"

        for price in [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]:
            s = _price_centrality_score(price)
            assert 0.0 <= s <= 1.0, f"price_centrality_score({price}) = {s}"


# ---------------------------------------------------------------------------
# ModelEvaluator tests
# ---------------------------------------------------------------------------


class TestModelEvaluator:
    def _make_evaluator(self):
        from agents.polymarket.top_bets.model_evaluator import ModelEvaluator

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        return ModelEvaluator(db_session=db), db

    async def test_model_evaluator_brier_score_known_values(self):
        """Two predictions with known values → verify Brier math."""
        from agents.polymarket.top_bets.model_evaluator import ModelEvaluator

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        # Pre-existing row: already in DB (scalar_one_or_none returns it directly).
        row = _FakePMModelEvaluation(model_type="ensemble", brier_score=0.0, accuracy=0.0, num_markets_tested=0)
        result_mock_row = MagicMock()
        result_mock_row.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result_mock_row)

        evaluator = ModelEvaluator(db_session=db)

        with patch("agents.polymarket.top_bets.model_evaluator.select", return_value=MagicMock()):
            # Record prediction 1: predicted=0.7, actual=1.0 → brier = (0.7-1.0)^2 = 0.09
            await evaluator.record_prediction("m1", predicted_yes=0.7, actual_yes=1.0)
            assert row.brier_score == pytest.approx(0.09, abs=1e-6)
            assert row.num_markets_tested == 1

            # Record prediction 2: predicted=0.3, actual=0.0 → brier = (0.3-0.0)^2 = 0.09
            # Running mean = (0.09 * 1 + 0.09) / 2 = 0.09
            await evaluator.record_prediction("m2", predicted_yes=0.3, actual_yes=0.0)
            assert row.brier_score == pytest.approx(0.09, abs=1e-6)
            assert row.num_markets_tested == 2

    async def test_model_evaluator_accuracy_tracking(self):
        """Correct predictions increment accuracy correctly."""
        from agents.polymarket.top_bets.model_evaluator import ModelEvaluator

        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        # Pre-existing row: already in DB.
        row = _FakePMModelEvaluation(model_type="ensemble", brier_score=0.0, accuracy=0.0, num_markets_tested=0)
        row_result = MagicMock()
        row_result.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=row_result)

        evaluator = ModelEvaluator(db_session=db)

        with patch("agents.polymarket.top_bets.model_evaluator.select", return_value=MagicMock()):
            # Prediction 1: predicted=0.8 (YES), actual=1.0 (YES) → correct=1.0
            await evaluator.record_prediction("m1", predicted_yes=0.8, actual_yes=1.0)
            assert row.accuracy == pytest.approx(1.0)

            # Prediction 2: predicted=0.8 (YES), actual=0.0 (NO) → wrong=0.0
            # Running accuracy = (1.0 * 1 + 0.0) / 2 = 0.5
            await evaluator.record_prediction("m2", predicted_yes=0.8, actual_yes=0.0)
            assert row.accuracy == pytest.approx(0.5)

    async def test_model_evaluator_compute_brier_score_no_data(self):
        """No evaluation data → returns 0.25 (uniform prior Brier score)."""
        from agents.polymarket.top_bets.model_evaluator import ModelEvaluator

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        evaluator = ModelEvaluator(db_session=db)
        with patch("agents.polymarket.top_bets.model_evaluator.select", return_value=MagicMock()):
            score = await evaluator.compute_brier_score("unknown_model")
        assert score == pytest.approx(0.25)

    async def test_model_evaluator_get_calibration_metrics(self):
        """get_calibration_metrics returns expected dict shape."""
        from agents.polymarket.top_bets.model_evaluator import ModelEvaluator

        db = AsyncMock()
        row = _FakePMModelEvaluation(
            model_type="ensemble",
            brier_score=0.09,
            accuracy=0.75,
            num_markets_tested=20,
        )
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result_mock)

        evaluator = ModelEvaluator(db_session=db)
        with patch("agents.polymarket.top_bets.model_evaluator.select", return_value=MagicMock()):
            metrics = await evaluator.get_calibration_metrics("ensemble")

        assert metrics["brier_score"] == pytest.approx(0.09)
        assert metrics["accuracy"] == pytest.approx(0.75)
        assert metrics["num_markets_tested"] == 20


# ---------------------------------------------------------------------------
# Pure helper function tests
# ---------------------------------------------------------------------------


class TestPureHelpers:
    def test_cot_parse_last_float(self):
        """_parse_last_float picks the last float and clamps to [0,1]."""
        from agents.polymarket.top_bets.cot_sampler import _parse_last_float

        assert _parse_last_float("The answer is 0.75 exactly.") == pytest.approx(0.75)
        assert _parse_last_float("First 0.3 then 0.8") == pytest.approx(0.8)
        assert _parse_last_float("No numbers here") is None
        assert _parse_last_float("Way above: 999") == pytest.approx(1.0)  # clamped
        assert _parse_last_float("Negative: 0") == pytest.approx(0.0)

    def test_trimmed_mean_drops_min_max(self):
        """_trimmed_mean with n>=5 drops the extreme values."""
        from agents.polymarket.top_bets.cot_sampler import _trimmed_mean

        # [0.1, 0.4, 0.5, 0.6, 0.9] → trimmed [0.4, 0.5, 0.6] → mean 0.5
        result = _trimmed_mean([0.1, 0.4, 0.5, 0.6, 0.9])
        assert result == pytest.approx(0.5)

    def test_trimmed_mean_with_fewer_than_5(self):
        """_trimmed_mean with <5 samples uses plain mean."""
        from agents.polymarket.top_bets.cot_sampler import _trimmed_mean

        result = _trimmed_mean([0.4, 0.6])
        assert result == pytest.approx(0.5)

    def test_std_dev_identical_samples(self):
        """Identical samples → std_dev = 0."""
        from agents.polymarket.top_bets.cot_sampler import _std_dev

        assert _std_dev([0.5, 0.5, 0.5, 0.5]) == pytest.approx(0.0)

    def test_std_dev_single_sample(self):
        """Single sample → std_dev = 0 (no spread)."""
        from agents.polymarket.top_bets.cot_sampler import _std_dev

        assert _std_dev([0.7]) == pytest.approx(0.0)
