"""Tests for inference client with circuit breaker."""

import time

import httpx
import pytest

from services.pipeline_worker.src.pipeline.inference_client import (
    CIRCUIT_COOLDOWN_SEC,
    CIRCUIT_FAILURE_THRESHOLD,
    CircuitBreaker,
    InferenceClient,
    PredictionResult,
)


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == "closed"
        assert cb.is_available() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker()
        for _ in range(CIRCUIT_FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.state == "open"
        assert cb.is_available() is False

    def test_success_resets_failures(self):
        cb = CircuitBreaker()
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.consecutive_failures == 0
        assert cb.state == "closed"

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker()
        for _ in range(CIRCUIT_FAILURE_THRESHOLD):
            cb.record_failure()
        assert cb.state == "open"

        # Simulate cooldown elapsed
        cb.opened_at = time.monotonic() - CIRCUIT_COOLDOWN_SEC - 1
        assert cb.is_available() is True
        assert cb.state == "half_open"

    def test_open_within_cooldown(self):
        cb = CircuitBreaker()
        for _ in range(CIRCUIT_FAILURE_THRESHOLD):
            cb.record_failure()
        # Cooldown not elapsed yet
        assert cb.is_available() is False


class TestInferenceClient:
    @pytest.mark.asyncio
    async def test_returns_skip_when_circuit_open(self):
        client = InferenceClient(inference_url="http://fake:8045")
        for _ in range(CIRCUIT_FAILURE_THRESHOLD):
            client._breaker.record_failure()

        async with httpx.AsyncClient() as http:
            result = await client.predict("AAPL", "agent-1", {}, http)
        assert result.prediction == "SKIP"
        assert result.reasoning == "circuit_breaker_open"

    @pytest.mark.asyncio
    async def test_returns_skip_on_http_error(self):
        client = InferenceClient(inference_url="http://localhost:1")

        async with httpx.AsyncClient() as http:
            result = await client.predict("AAPL", "agent-1", {}, http)
        assert result.prediction == "SKIP"
        assert client._breaker.consecutive_failures == 1

    def test_prediction_result_defaults(self):
        pr = PredictionResult(prediction="TRADE", confidence=0.9)
        assert pr.model_used is None
        assert pr.reasoning is None
