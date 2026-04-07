"""
ResolutionRiskScorer (F9, Polymarket v1.0 — Phase 5).

Reference:
- docs/architecture/polymarket-tab.md sections 3 (F9), 4.6, 9 (Phase 5), 10 (R-B).
- docs/prd/polymarket-tab.md F9.

Goal
====
For every discovered PM market, produce a 0..1 *resolution risk* score and a
hard `tradeable` boolean. The risk chain (Phase 6) refuses to submit any
order whose target market does not have a recent score with `tradeable=True`.

The score is the linear combination of three structural signals plus an LLM
ambiguity grade of the question wording:

    final = clip01(
          w_oracle    * oracle_risk
        + w_disputes  * dispute_risk
        + w_expiry    * expiry_risk
        + w_ambiguity * llm_ambiguity_score
    )

Higher == riskier. `tradeable = final < TRADEABLE_THRESHOLD`.

The LLM call goes through `shared/llm/client.py` (Ollama) in JSON mode and
asks for a single float and a one-line rationale. If the LLM is unavailable
or returns garbage, we fall back to a conservative ambiguity prior of 0.5
and mark the rationale accordingly — the structural signals still apply.

This module is pure: it takes a market dataclass / row, an optional LLM
client, and an optional SQLAlchemy `Session`. Persistence is opt-in via
`score_and_persist()` so unit tests can exercise the scoring logic without
a database.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol

from sqlalchemy.orm import Session

from shared.db.models.polymarket import PMMarket, PMResolutionScore
from shared.llm.client import OllamaClient

logger = logging.getLogger(__name__)

MODEL_VERSION = "f9-v1.0"

# Hard gate: anything at or above this combined score is non-tradeable.
TRADEABLE_THRESHOLD = 0.55

# Combination weights. Tuned so that *either* a maxed dispute history
# (`prior_disputes >= 3` -> dispute_risk=1.0) *or* a near-maxed LLM ambiguity
# grade (~0.95) is sufficient on its own to push an otherwise-clean UMA market
# across the TRADEABLE_THRESHOLD gate. The weights intentionally do not sum to
# 1.0; the final score is clipped to [0, 1] in `_clip01`.
W_ORACLE = 0.10
W_DISPUTES = 0.50
W_EXPIRY = 0.05
W_AMBIGUITY = 0.57

# Oracle risk priors (higher == worse).
ORACLE_PRIORS: dict[str, float] = {
    "uma": 0.20,           # battle-tested but disputable
    "uma_oo": 0.20,
    "centralized": 0.55,   # single-operator resolution
    "manual": 0.70,
    "unknown": 0.65,
    None: 0.65,            # type: ignore[dict-item]
}

# Default LLM ambiguity prior used when the gateway is unreachable.
LLM_FALLBACK_AMBIGUITY = 0.50
LLM_FALLBACK_RATIONALE = "llm_unavailable: defaulted to neutral prior"

LLM_SYSTEM_PROMPT = (
    "You are grading prediction-market questions for resolution ambiguity. "
    "Reply with strict JSON only, no prose, of the shape "
    '{"ambiguity": <float 0..1>, "rationale": "<short reason>"}. '
    "0 means the question has a single, objective, verifiable answer. "
    "1 means the question is subjective, vague, or has multiple plausible interpretations."
)


class _LLMLike(Protocol):
    async def generate(  # pragma: no cover - protocol
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> Any: ...


@dataclass(frozen=True)
class MarketInput:
    """Lightweight view of a PM market for scoring.

    Decoupled from the ORM so the scorer can be exercised in unit tests
    and called from the discovery scanner before a row is persisted.
    """

    market_id: Optional[uuid.UUID]
    question: str
    oracle_type: Optional[str]
    resolution_source: Optional[str]
    expiry: Optional[datetime]
    prior_disputes: int = 0

    @classmethod
    def from_orm(cls, m: PMMarket, prior_disputes: int = 0) -> "MarketInput":
        return cls(
            market_id=m.id,
            question=m.question,
            oracle_type=m.oracle_type,
            resolution_source=m.resolution_source,
            expiry=m.expiry,
            prior_disputes=prior_disputes,
        )


@dataclass(frozen=True)
class ResolutionRiskFactors:
    oracle_risk: float
    dispute_risk: float
    expiry_risk: float
    llm_ambiguity_score: float
    llm_rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "oracle_risk": self.oracle_risk,
            "dispute_risk": self.dispute_risk,
            "expiry_risk": self.expiry_risk,
            "llm_ambiguity_score": self.llm_ambiguity_score,
            "llm_rationale": self.llm_rationale,
        }


@dataclass(frozen=True)
class ResolutionRiskResult:
    market_id: Optional[uuid.UUID]
    final_score: float
    tradeable: bool
    factors: ResolutionRiskFactors
    model_version: str = MODEL_VERSION
    scored_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _clip01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _oracle_risk(oracle_type: Optional[str]) -> float:
    if oracle_type is None:
        return ORACLE_PRIORS[None]  # type: ignore[index]
    return ORACLE_PRIORS.get(oracle_type.lower(), ORACLE_PRIORS["unknown"])


def _dispute_risk(prior_disputes: int) -> float:
    # 0 disputes -> 0.0; 1 -> 0.4; 2 -> 0.7; 3+ -> 1.0.
    if prior_disputes <= 0:
        return 0.0
    if prior_disputes == 1:
        return 0.4
    if prior_disputes == 2:
        return 0.7
    return 1.0


def _expiry_risk(expiry: Optional[datetime], *, now: Optional[datetime] = None) -> float:
    """Markets that resolve very soon or very far away are slightly riskier."""
    if expiry is None:
        return 0.5
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    delta = expiry - now
    if delta <= timedelta(0):
        return 1.0  # already expired / unresolved == max risk
    if delta < timedelta(hours=24):
        return 0.6
    if delta < timedelta(days=7):
        return 0.2
    if delta < timedelta(days=180):
        return 0.1
    return 0.4  # very long-dated markets get a small bump


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_llm_json(text: str) -> tuple[Optional[float], Optional[str]]:
    """Best-effort JSON extraction. Returns (ambiguity, rationale)."""
    if not text:
        return None, None
    candidate = text.strip()
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        match = _JSON_RE.search(candidate)
        if not match:
            return None, None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None, None
    if not isinstance(data, dict):
        return None, None
    raw = data.get("ambiguity")
    rationale = data.get("rationale")
    try:
        amb = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        amb = None
    if amb is not None:
        amb = _clip01(amb)
    if rationale is not None and not isinstance(rationale, str):
        rationale = str(rationale)
    return amb, rationale


class ResolutionRiskScorer:
    """Combines structural risk with LLM ambiguity grading.

    Stateless apart from the injected LLM client. Safe to share across
    coroutines because the underlying `OllamaClient` is async-safe.
    """

    def __init__(
        self,
        llm_client: Optional[_LLMLike] = None,
        *,
        model: Optional[str] = None,
        tradeable_threshold: float = TRADEABLE_THRESHOLD,
        now_fn=None,
    ) -> None:
        self._llm = llm_client if llm_client is not None else OllamaClient()
        self._model = model
        self._threshold = tradeable_threshold
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    async def _grade_ambiguity(self, question: str) -> tuple[float, str]:
        prompt = (
            "Grade the following prediction-market question for resolution ambiguity. "
            "Question: " + (question or "").strip()
        )
        try:
            resp = await self._llm.generate(
                prompt=prompt,
                model=self._model,
                system=LLM_SYSTEM_PROMPT,
                temperature=0.0,
                max_tokens=200,
                json_mode=True,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("F9 LLM call failed: %s", exc)
            return LLM_FALLBACK_AMBIGUITY, LLM_FALLBACK_RATIONALE

        text = getattr(resp, "text", "") or ""
        done = getattr(resp, "done", True)
        if not done or not text:
            return LLM_FALLBACK_AMBIGUITY, LLM_FALLBACK_RATIONALE

        amb, rationale = _parse_llm_json(text)
        if amb is None:
            logger.warning("F9 LLM returned unparseable payload: %r", text[:200])
            return LLM_FALLBACK_AMBIGUITY, LLM_FALLBACK_RATIONALE
        return amb, rationale or "ok"

    async def score(self, market: MarketInput) -> ResolutionRiskResult:
        oracle_risk = _oracle_risk(market.oracle_type)
        dispute_risk = _dispute_risk(market.prior_disputes)
        expiry_risk = _expiry_risk(market.expiry, now=self._now_fn())
        amb, rationale = await self._grade_ambiguity(market.question)

        final = _clip01(
            W_ORACLE * oracle_risk
            + W_DISPUTES * dispute_risk
            + W_EXPIRY * expiry_risk
            + W_AMBIGUITY * amb
        )
        tradeable = final < self._threshold

        factors = ResolutionRiskFactors(
            oracle_risk=oracle_risk,
            dispute_risk=dispute_risk,
            expiry_risk=expiry_risk,
            llm_ambiguity_score=amb,
            llm_rationale=rationale,
        )
        result = ResolutionRiskResult(
            market_id=market.market_id,
            final_score=final,
            tradeable=tradeable,
            factors=factors,
            scored_at=self._now_fn(),
        )
        logger.info(
            "F9 scored market_id=%s final=%.3f tradeable=%s factors=%s",
            market.market_id,
            final,
            tradeable,
            factors.as_dict(),
        )
        return result

    async def score_and_persist(
        self,
        market: MarketInput,
        session: Session,
    ) -> ResolutionRiskResult:
        """Score and write a `pm_resolution_scores` row in the same call."""
        if market.market_id is None:
            raise ValueError("score_and_persist requires market.market_id")
        result = await self.score(market)
        row = PMResolutionScore(
            pm_market_id=market.market_id,
            oracle_type=market.oracle_type,
            prior_disputes=market.prior_disputes,
            llm_ambiguity_score=result.factors.llm_ambiguity_score,
            llm_rationale=result.factors.llm_rationale,
            final_score=result.final_score,
            tradeable=result.tradeable,
            scored_at=result.scored_at,
            model_version=result.model_version,
        )
        session.add(row)
        session.flush()
        return result


__all__ = [
    "MODEL_VERSION",
    "TRADEABLE_THRESHOLD",
    "MarketInput",
    "ResolutionRiskFactors",
    "ResolutionRiskResult",
    "ResolutionRiskScorer",
]
