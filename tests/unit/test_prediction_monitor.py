"""Unit tests for the prediction-monitor service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from shared.db.models.feature_store import Prediction

AGENT_A = uuid.uuid4()
AGENT_B = uuid.uuid4()
NOW = datetime.now(timezone.utc)


class TestIsCorrect:
    def test_trade_win(self):
        from services.prediction_monitor.src.main import _is_correct

        assert _is_correct("TRADE", "WIN") is True

    def test_trade_loss(self):
        from services.prediction_monitor.src.main import _is_correct

        assert _is_correct("TRADE", "LOSS") is False

    def test_skip_loss(self):
        from services.prediction_monitor.src.main import _is_correct

        assert _is_correct("SKIP", "LOSS") is True

    def test_skip_win(self):
        from services.prediction_monitor.src.main import _is_correct

        assert _is_correct("SKIP", "WIN") is False


class TestComputeWindowMetrics:
    def test_empty_list(self):
        from services.prediction_monitor.src.main import _compute_window_metrics

        m = _compute_window_metrics([])
        assert m.total == 0
        assert m.accuracy == 0.0

    def test_no_resolved(self):
        from services.prediction_monitor.src.main import _compute_window_metrics

        pred = Prediction(
            agent_id=AGENT_A, ticker="AAPL", prediction="TRADE",
            confidence=0.8, predicted_at=NOW, actual_outcome=None,
        )
        m = _compute_window_metrics([pred])
        assert m.total == 1
        assert m.correct == 0
        assert m.accuracy == 0.0

    def test_perfect_accuracy(self):
        from services.prediction_monitor.src.main import _compute_window_metrics

        preds = [
            Prediction(
                agent_id=AGENT_A, ticker="AAPL", prediction="TRADE",
                confidence=0.9, predicted_at=NOW, actual_outcome="WIN",
            ),
            Prediction(
                agent_id=AGENT_A, ticker="TSLA", prediction="SKIP",
                confidence=0.7, predicted_at=NOW, actual_outcome="LOSS",
            ),
        ]
        m = _compute_window_metrics(preds)
        assert m.total == 2
        assert m.correct == 2
        assert m.accuracy == 1.0
        assert m.precision == 1.0

    def test_mixed_accuracy(self):
        from services.prediction_monitor.src.main import _compute_window_metrics

        preds = [
            Prediction(
                agent_id=AGENT_A, ticker="AAPL", prediction="TRADE",
                confidence=0.9, predicted_at=NOW, actual_outcome="WIN",
            ),
            Prediction(
                agent_id=AGENT_A, ticker="TSLA", prediction="TRADE",
                confidence=0.6, predicted_at=NOW, actual_outcome="LOSS",
            ),
        ]
        m = _compute_window_metrics(preds)
        assert m.total == 2
        assert m.correct == 1
        assert m.accuracy == 0.5
        assert m.precision == 0.5

    def test_avg_confidence(self):
        from services.prediction_monitor.src.main import _compute_window_metrics

        preds = [
            Prediction(
                agent_id=AGENT_A, ticker="AAPL", prediction="TRADE",
                confidence=0.8, predicted_at=NOW, actual_outcome="WIN",
            ),
            Prediction(
                agent_id=AGENT_A, ticker="TSLA", prediction="TRADE",
                confidence=0.6, predicted_at=NOW, actual_outcome="WIN",
            ),
        ]
        m = _compute_window_metrics(preds)
        assert m.avg_confidence == pytest.approx(0.7, abs=0.01)

    def test_precision_zero_when_no_trade_predictions(self):
        from services.prediction_monitor.src.main import _compute_window_metrics

        preds = [
            Prediction(
                agent_id=AGENT_A, ticker="AAPL", prediction="SKIP",
                confidence=0.8, predicted_at=NOW, actual_outcome="WIN",
            ),
        ]
        m = _compute_window_metrics(preds)
        assert m.precision == 0.0


class TestOutcomeValidation:
    @pytest.mark.asyncio
    async def test_invalid_outcome_rejected(self):
        from services.prediction_monitor.src.main import OutcomePayload

        with pytest.raises(Exception):
            OutcomePayload(actual_outcome="MAYBE", actual_pnl=50.0)

    @pytest.mark.asyncio
    async def test_valid_outcome_win(self):
        from services.prediction_monitor.src.main import OutcomePayload

        p = OutcomePayload(actual_outcome="WIN", actual_pnl=100.0)
        assert p.actual_outcome == "WIN"
        assert p.actual_pnl == 100.0

    @pytest.mark.asyncio
    async def test_valid_outcome_loss(self):
        from services.prediction_monitor.src.main import OutcomePayload

        p = OutcomePayload(actual_outcome="LOSS", actual_pnl=-50.0)
        assert p.actual_outcome == "LOSS"
        assert p.actual_pnl == -50.0


class TestWindowMetricsModel:
    def test_defaults(self):
        from services.prediction_monitor.src.main import WindowMetrics

        m = WindowMetrics()
        assert m.total == 0
        assert m.correct == 0
        assert m.accuracy == 0.0
        assert m.precision == 0.0
        assert m.avg_confidence == 0.0

    def test_model_dump(self):
        from services.prediction_monitor.src.main import WindowMetrics

        m = WindowMetrics(total=10, correct=7, accuracy=0.7, precision=0.75, avg_confidence=0.8)
        d = m.model_dump()
        assert d == {"total": 10, "correct": 7, "accuracy": 0.7, "precision": 0.75, "avg_confidence": 0.8}


class TestNowUtc:
    def test_returns_utc(self):
        from services.prediction_monitor.src.main import _now_utc

        result = _now_utc()
        assert result.tzinfo == timezone.utc


class TestEndpointValidation:
    @pytest.mark.asyncio
    async def test_health_endpoint(self):
        from httpx import ASGITransport, AsyncClient

        from services.prediction_monitor.src.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "phoenix-prediction-monitor"

    @pytest.mark.asyncio
    async def test_outcome_invalid_payload_422(self):
        from httpx import ASGITransport, AsyncClient

        from services.prediction_monitor.src.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/predictions/1/outcome",
                json={"actual_outcome": "MAYBE", "actual_pnl": 50.0},
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_outcome_missing_fields_422(self):
        from httpx import ASGITransport, AsyncClient

        from services.prediction_monitor.src.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/predictions/1/outcome",
                json={"actual_pnl": 50.0},
            )
        assert resp.status_code == 422
