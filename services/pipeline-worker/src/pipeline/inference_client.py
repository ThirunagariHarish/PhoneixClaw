"""Inference client with circuit breaker — HTTP calls to the inference service."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_SEC = 30.0


@dataclass
class PredictionResult:
    prediction: str  # "TRADE" or "SKIP"
    confidence: float = 0.0
    model_used: Optional[str] = None
    reasoning: Optional[str] = None


@dataclass
class CircuitBreaker:
    consecutive_failures: int = 0
    opened_at: float = 0.0
    state: str = "closed"  # closed | open | half_open

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
            self.state = "open"
            self.opened_at = time.monotonic()
            logger.warning("Circuit breaker OPEN after %d failures", self.consecutive_failures)

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.state = "closed"

    def is_available(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            elapsed = time.monotonic() - self.opened_at
            if elapsed >= CIRCUIT_COOLDOWN_SEC:
                self.state = "half_open"
                return True
            return False
        # half_open: allow one request through
        return True


@dataclass
class InferenceClient:
    inference_url: str = ""
    _breaker: CircuitBreaker = field(default_factory=CircuitBreaker)

    @property
    def circuit_state(self) -> str:
        return self._breaker.state

    async def predict(
        self,
        ticker: str,
        agent_id: str,
        signal_features: dict,
        http_client: httpx.AsyncClient,
    ) -> PredictionResult:
        if not self._breaker.is_available():
            logger.info("Circuit open — returning SKIP for %s", ticker)
            return PredictionResult(
                prediction="SKIP",
                confidence=0.1,
                reasoning="circuit_breaker_open",
            )

        try:
            resp = await http_client.post(
                f"{self.inference_url}/predict",
                json={
                    "ticker": ticker,
                    "agent_id": agent_id,
                    "signal_features": signal_features,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            self._breaker.record_success()
            return PredictionResult(
                prediction=data.get("prediction", "SKIP"),
                confidence=float(data.get("confidence", 0.0)),
                model_used=data.get("model_used"),
                reasoning=data.get("reasoning"),
            )
        except Exception as exc:
            logger.warning("Inference call failed for %s: %s", ticker, exc)
            self._breaker.record_failure()
            return PredictionResult(
                prediction="SKIP",
                confidence=0.1,
                reasoning=f"inference_error: {exc}",
            )
