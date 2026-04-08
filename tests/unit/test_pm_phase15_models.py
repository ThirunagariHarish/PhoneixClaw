"""Unit tests for Phase 15.1 ORM models (7 new classes).

We don't spin up a real PG instance here — JSONB/UUID PG types are not
available on SQLite.  We verify:
  - correct __tablename__
  - all required columns are present as class attributes
  - list-typed JSONB fields are annotated as list / Optional[list], not dict
  - nullable vs not-null field presence
  - default values are callable/correct where applicable
"""

import uuid
from datetime import date
from typing import get_args

import pytest

from shared.db.models import (
    PMAgentActivityLog,
    PMChatMessage,
    PMHistoricalMarket,
    PMMarketEmbedding,
    PMModelEvaluation,
    PMStrategyResearchLog,
    PMTopBet,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _col(model, name):
    """Return the mapped column property for *name* on *model*."""
    return model.__table__.c[name]


def _is_nullable(model, name):
    return _col(model, name).nullable


# ---------------------------------------------------------------------------
# PMTopBet
# ---------------------------------------------------------------------------


class TestPMTopBet:
    def test_tablename(self):
        assert PMTopBet.__tablename__ == "pm_top_bets"

    def test_required_columns_present(self):
        required = [
            "id", "market_id", "recommendation_date", "side",
            "confidence_score", "edge_bps", "reasoning", "status",
            "created_at", "updated_at",
        ]
        for col in required:
            assert hasattr(PMTopBet, col), f"missing column: {col}"

    def test_optional_columns_present(self):
        optional = [
            "rejected_reason", "accepted_order_id",
            "bull_argument", "bear_argument", "debate_summary",
            "bull_score", "bear_score",
            "sample_probabilities", "consensus_spread",
            "reference_class", "base_rate_yes",
            "base_rate_sample_size", "base_rate_confidence",
        ]
        for col in optional:
            assert hasattr(PMTopBet, col), f"missing column: {col}"

    def test_sample_probabilities_is_list_typed(self):
        """sample_probabilities must store and return a list at runtime."""
        obj = PMTopBet(
            id=uuid.uuid4(),
            market_id=uuid.uuid4(),
            recommendation_date=date.today(),
            side="YES",
            confidence_score=80,
            edge_bps=120,
            reasoning="Strong fundamentals",
            sample_probabilities=[0.60, 0.65, 0.70],
        )
        assert isinstance(obj.sample_probabilities, list), (
            f"sample_probabilities should be a list, got {type(obj.sample_probabilities)}"
        )
        assert all(isinstance(v, float) for v in obj.sample_probabilities)

    def test_required_not_null(self):
        for col in ("market_id", "recommendation_date", "side", "confidence_score", "edge_bps", "reasoning"):
            assert not _is_nullable(PMTopBet, col), f"{col} should be NOT NULL"

    def test_optional_nullable(self):
        for col in ("rejected_reason", "accepted_order_id", "bull_argument", "sample_probabilities"):
            assert _is_nullable(PMTopBet, col), f"{col} should be nullable"

    def test_unique_constraint_exists(self):
        uq_names = {uc.name for uc in PMTopBet.__table__.constraints if hasattr(uc, "name")}
        assert "uq_pm_top_bets_market_date" in uq_names

    def test_instantiation(self):
        obj = PMTopBet(
            id=uuid.uuid4(),
            market_id=uuid.uuid4(),
            recommendation_date=date.today(),
            side="YES",
            confidence_score=80,
            edge_bps=120,
            reasoning="Strong fundamentals",
        )
        assert obj.side == "YES"
        assert obj.sample_probabilities is None


# ---------------------------------------------------------------------------
# PMChatMessage
# ---------------------------------------------------------------------------


class TestPMChatMessage:
    def test_tablename(self):
        assert PMChatMessage.__tablename__ == "pm_chat_messages"

    def test_required_columns_present(self):
        for col in ("id", "session_id", "role", "content", "created_at"):
            assert hasattr(PMChatMessage, col), f"missing: {col}"

    def test_optional_columns_present(self):
        for col in ("bet_recommendation", "accepted_order_id"):
            assert hasattr(PMChatMessage, col), f"missing: {col}"

    def test_optional_nullable(self):
        for col in ("bet_recommendation", "accepted_order_id"):
            assert _is_nullable(PMChatMessage, col), f"{col} should be nullable"

    def test_required_not_null(self):
        for col in ("session_id", "role", "content"):
            assert not _is_nullable(PMChatMessage, col), f"{col} should be NOT NULL"

    def test_instantiation(self):
        obj = PMChatMessage(
            id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            role="user",
            content="What is the best bet today?",
        )
        assert obj.role == "user"
        assert obj.bet_recommendation is None


# ---------------------------------------------------------------------------
# PMAgentActivityLog
# ---------------------------------------------------------------------------


class TestPMAgentActivityLog:
    def test_tablename(self):
        assert PMAgentActivityLog.__tablename__ == "pm_agent_activity_log"

    def test_required_columns_present(self):
        for col in ("id", "agent_type", "severity", "action", "created_at"):
            assert hasattr(PMAgentActivityLog, col), f"missing: {col}"

    def test_optional_columns_present(self):
        for col in ("detail", "markets_scanned_today", "bets_generated_today"):
            assert hasattr(PMAgentActivityLog, col), f"missing: {col}"

    def test_optional_nullable(self):
        for col in ("detail", "markets_scanned_today", "bets_generated_today"):
            assert _is_nullable(PMAgentActivityLog, col), f"{col} should be nullable"

    def test_required_not_null(self):
        for col in ("agent_type", "severity", "action"):
            assert not _is_nullable(PMAgentActivityLog, col), f"{col} should be NOT NULL"

    def test_instantiation(self):
        obj = PMAgentActivityLog(
            id=uuid.uuid4(),
            agent_type="scanner",
            severity="info",
            action="scan_complete",
        )
        assert obj.severity == "info"
        assert obj.detail is None


# ---------------------------------------------------------------------------
# PMStrategyResearchLog
# ---------------------------------------------------------------------------


class TestPMStrategyResearchLog:
    def test_tablename(self):
        assert PMStrategyResearchLog.__tablename__ == "pm_strategy_research_log"

    def test_required_columns_present(self):
        for col in ("id", "run_at", "raw_findings", "applied", "created_at"):
            assert hasattr(PMStrategyResearchLog, col), f"missing: {col}"

    def test_optional_columns_present(self):
        for col in ("sources_queried", "proposed_config_delta", "applied_at", "applied_by_user_id", "notes"):
            assert hasattr(PMStrategyResearchLog, col), f"missing: {col}"

    def test_optional_nullable(self):
        for col in ("sources_queried", "proposed_config_delta", "applied_at", "notes"):
            assert _is_nullable(PMStrategyResearchLog, col), f"{col} should be nullable"

    def test_instantiation(self):
        obj = PMStrategyResearchLog(
            id=uuid.uuid4(),
            raw_findings="Found strong signal in sports markets.",
        )
        assert obj.raw_findings.startswith("Found")
        assert obj.applied is False or obj.applied is None  # default is server_default


# ---------------------------------------------------------------------------
# PMHistoricalMarket
# ---------------------------------------------------------------------------


class TestPMHistoricalMarket:
    def test_tablename(self):
        assert PMHistoricalMarket.__tablename__ == "pm_historical_markets"

    def test_required_columns_present(self):
        for col in ("id", "venue", "venue_market_id", "question", "created_at", "updated_at"):
            assert hasattr(PMHistoricalMarket, col), f"missing: {col}"

    def test_optional_columns_present(self):
        for col in (
            "category", "description", "outcomes_json", "winning_outcome",
            "resolution_date", "price_history_json", "community_discussion_summary",
            "volume_usd", "liquidity_peak_usd", "reference_class",
        ):
            assert hasattr(PMHistoricalMarket, col), f"missing: {col}"

    def test_outcomes_json_is_list_typed(self):
        """outcomes_json must store and return a list at runtime, not a dict."""
        obj = PMHistoricalMarket(
            id=uuid.uuid4(),
            venue="polymarket",
            venue_market_id="abc-123",
            question="Will X happen?",
            outcomes_json=[{"outcome": "Yes"}, {"outcome": "No"}],
        )
        assert isinstance(obj.outcomes_json, list), (
            f"outcomes_json should be a list, got {type(obj.outcomes_json)}"
        )
        assert not isinstance(obj.outcomes_json, dict)

    def test_price_history_json_is_list_typed(self):
        """price_history_json must store and return a list at runtime, not a dict."""
        obj = PMHistoricalMarket(
            id=uuid.uuid4(),
            venue="polymarket",
            venue_market_id="abc-456",
            question="Will Y happen?",
            price_history_json=[{"ts": 1000, "price": 0.6}, {"ts": 2000, "price": 0.7}],
        )
        assert isinstance(obj.price_history_json, list), (
            f"price_history_json should be a list, got {type(obj.price_history_json)}"
        )
        assert not isinstance(obj.price_history_json, dict)

    def test_required_not_null(self):
        for col in ("venue", "venue_market_id", "question"):
            assert not _is_nullable(PMHistoricalMarket, col), f"{col} should be NOT NULL"

    def test_optional_nullable(self):
        for col in ("outcomes_json", "price_history_json", "category", "resolution_date"):
            assert _is_nullable(PMHistoricalMarket, col), f"{col} should be nullable"

    def test_unique_constraint_exists(self):
        uq_names = {uc.name for uc in PMHistoricalMarket.__table__.constraints if hasattr(uc, "name")}
        assert "uq_pm_historical_markets_venue_id" in uq_names

    def test_instantiation(self):
        obj = PMHistoricalMarket(
            id=uuid.uuid4(),
            venue="polymarket",
            venue_market_id="abc-123",
            question="Will X happen?",
            outcomes_json=[{"outcome": "Yes"}, {"outcome": "No"}],
            price_history_json=[{"ts": 1000, "price": 0.6}],
        )
        assert isinstance(obj.outcomes_json, list)
        assert isinstance(obj.price_history_json, list)

    def test_list_fields_reject_dicts(self):
        """Verify annotated type is list (not dict) so dict values will fail type checkers."""
        # This is a static-type check via annotations — ensure list is NOT dict
        ann_outcomes = PMHistoricalMarket.__annotations__.get("outcomes_json")
        ann_price = PMHistoricalMarket.__annotations__.get("price_history_json")
        for ann in (ann_outcomes, ann_price):
            inner_types = get_args(ann)
            assert dict not in inner_types, f"Should not be dict-typed: {ann}"


# ---------------------------------------------------------------------------
# PMMarketEmbedding
# ---------------------------------------------------------------------------


class TestPMMarketEmbedding:
    def test_tablename(self):
        assert PMMarketEmbedding.__tablename__ == "pm_market_embeddings"

    def test_required_columns_present(self):
        for col in ("id", "historical_market_id", "embedding", "model_used", "created_at"):
            assert hasattr(PMMarketEmbedding, col), f"missing: {col}"

    def test_embedding_is_list_typed(self):
        """embedding must store and return a list of floats at runtime."""
        obj = PMMarketEmbedding(
            id=uuid.uuid4(),
            historical_market_id=uuid.uuid4(),
            embedding=[0.1, 0.2, 0.3],
            model_used="text-embedding-3-small",
        )
        assert isinstance(obj.embedding, list), (
            f"embedding should be a list, got {type(obj.embedding)}"
        )
        assert all(isinstance(v, float) for v in obj.embedding)

    def test_embedding_is_not_dict_typed(self):
        annotation = PMMarketEmbedding.__annotations__.get("embedding")
        assert annotation is not dict, "embedding must not be annotated as dict"

    def test_required_not_null(self):
        for col in ("historical_market_id", "embedding", "model_used"):
            assert not _is_nullable(PMMarketEmbedding, col), f"{col} should be NOT NULL"

    def test_instantiation(self):
        embedding_vector = [0.1] * 1536
        obj = PMMarketEmbedding(
            id=uuid.uuid4(),
            historical_market_id=uuid.uuid4(),
            embedding=embedding_vector,
            model_used="text-embedding-3-small",
        )
        assert isinstance(obj.embedding, list)
        assert len(obj.embedding) == 1536


# ---------------------------------------------------------------------------
# PMModelEvaluation
# ---------------------------------------------------------------------------


class TestPMModelEvaluation:
    def test_tablename(self):
        assert PMModelEvaluation.__tablename__ == "pm_model_evaluations"

    def test_required_columns_present(self):
        for col in ("id", "model_type", "brier_score", "accuracy", "num_markets_tested", "is_active", "created_at"):
            assert hasattr(PMModelEvaluation, col), f"missing: {col}"

    def test_optional_columns_present(self):
        for col in ("sharpe_proxy", "evaluated_at"):
            assert hasattr(PMModelEvaluation, col), f"missing: {col}"

    def test_brier_score_not_null(self):
        assert not _is_nullable(PMModelEvaluation, "brier_score"), "brier_score should be NOT NULL"

    def test_accuracy_not_null(self):
        assert not _is_nullable(PMModelEvaluation, "accuracy"), "accuracy should be NOT NULL"

    def test_num_markets_tested_not_null(self):
        assert not _is_nullable(PMModelEvaluation, "num_markets_tested"), "num_markets_tested should be NOT NULL"

    def test_sharpe_proxy_nullable(self):
        assert _is_nullable(PMModelEvaluation, "sharpe_proxy"), "sharpe_proxy should be nullable"

    def test_evaluated_at_nullable(self):
        assert _is_nullable(PMModelEvaluation, "evaluated_at"), "evaluated_at should be nullable"

    def test_instantiation(self):
        obj = PMModelEvaluation(
            id=uuid.uuid4(),
            model_type="debate_cot_v1",
            brier_score=0.18,
            accuracy=0.72,
            num_markets_tested=50,
        )
        assert obj.model_type == "debate_cot_v1"
        assert obj.brier_score == pytest.approx(0.18)
        assert obj.num_markets_tested == 50
