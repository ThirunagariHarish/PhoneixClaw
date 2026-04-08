"""LLM Scorer — orchestrates the full Scorer Chain (Phase 15.4).

Chains:
  1. ReferenceClassScorer  → base-rate anchor
  2. CoTSampler            → LLM self-consistency estimate (N=5 parallel)
  3. DebateScorer          → Bull/Bear/Judge refinement (optional)
  4. Weighted blend        → final YES probability

Reference:
    docs/architecture/polymarket-phase15.md  § 8-9 (Phase 15.4 + Scorer Chain)
    docs/prd/polymarket-phase15.md           F15-F (LLM RAG inference)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agents.polymarket.data.embedding_store import EmbeddingStore
from agents.polymarket.top_bets.cot_sampler import CoTResult, CoTSampler
from agents.polymarket.top_bets.debate_scorer import DebateResult, DebateScorer
from agents.polymarket.top_bets.reference_class import ReferenceClassResult, ReferenceClassScorer

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG: dict = {
    "scorer": {
        "cot_samples": 5,
        "debate_top_k": 20,
        "reference_class_weight": 0.3,
        "llm_weight": 0.5,
        "heuristic_weight": 0.2,
        "min_confidence_threshold": 0.55,
        "max_daily_debate_calls": 100,
    },
    "llm": {
        "model": "claude-3-5-haiku-20241022",
        "temperature": 0.3,
        "max_tokens": 1024,
    },
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class LLMScorerResult:
    """Full output of :class:`LLMScorer.score_market`."""

    yes_probability: float
    """Final blended YES probability (0.0–1.0)."""

    no_probability: float
    """``1 - yes_probability``."""

    confidence: float
    """Overall confidence (``1 - cot_std_dev``); higher is more reliable."""

    reference_class_result: ReferenceClassResult
    """Result from the reference-class stage."""

    cot_result: CoTResult
    """Result from the CoT sampling stage."""

    debate_result: DebateResult | None
    """Result from the debate stage, or ``None`` if debate was skipped."""

    final_reasoning: str
    """Human-readable summary of how the final probability was derived."""


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class LLMScorer:
    """Orchestrate the full Scorer Chain for one prediction market question.

    Args:
        embedding_store: Used by :class:`ReferenceClassScorer` for RAG look-ups.
        llm_client:      Injected LLM client (never instantiated here).
        config:          Full config dict (``scorer`` and ``llm`` keys).
                         Falls back to :data:`_DEFAULT_CONFIG` for missing keys.
    """

    def __init__(self, embedding_store: EmbeddingStore, llm_client: object, config: dict) -> None:
        self._embedding_store = embedding_store
        self._llm = llm_client
        self._cfg = _merge_config(config)

        self._ref_scorer = ReferenceClassScorer(embedding_store)
        self._cot_sampler = CoTSampler(llm_client, self._cfg)
        self._debate_scorer = DebateScorer(llm_client, self._cfg)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def score_market(self, market: dict, run_debate: bool = False) -> LLMScorerResult:
        """Score one market through the full chain.

        Args:
            market:     Dict with at minimum ``question`` and optionally
                        ``category``, ``description``, and ``context`` keys.
            run_debate: Whether to run the Bull/Bear/Judge debate stage.

        Returns:
            :class:`LLMScorerResult` with all intermediate results and the
            final blended probability.
        """
        scorer_cfg = self._cfg.get("scorer", {})
        ref_weight: float = scorer_cfg.get("reference_class_weight", 0.3)
        llm_weight: float = scorer_cfg.get("llm_weight", 0.5)
        n_samples: int = scorer_cfg.get("cot_samples", 5)

        question: str = market.get("question", "")
        category: str = market.get("category", "")
        context: str = _build_context(market)

        # --- Stage 1: Reference Class ---
        ref_result = await self._ref_scorer.score(question, category=category)

        # --- Stage 2: CoT Sampling ---
        cot_result = await self._cot_sampler.sample(question, context, n=n_samples)

        # --- Stage 3: Debate (optional) ---
        debate_result: DebateResult | None = None
        if run_debate:
            debate_result = await self._debate_scorer.score(question, context, cot_result.mean_yes_prob)

        # --- Stage 4: Weighted Blend ---
        final_yes = _blend(
            ref_rate=ref_result.base_rate_yes,
            cot_mean=cot_result.mean_yes_prob,
            debate_result=debate_result,
            ref_weight=ref_weight,
            llm_weight=llm_weight,
        )
        final_yes = max(0.0, min(1.0, final_yes))

        # Confidence is the inverse of CoT disagreement.
        confidence = max(0.0, 1.0 - cot_result.std_dev)

        reasoning = _build_reasoning(question, ref_result, cot_result, debate_result, final_yes, confidence)

        logger.info(
            "llm_scorer: question='%s' final_yes=%.3f confidence=%.3f debate=%s",
            question[:60],
            final_yes,
            confidence,
            run_debate,
        )
        return LLMScorerResult(
            yes_probability=final_yes,
            no_probability=1.0 - final_yes,
            confidence=confidence,
            reference_class_result=ref_result,
            cot_result=cot_result,
            debate_result=debate_result,
            final_reasoning=reasoning,
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _blend(
    *,
    ref_rate: float,
    cot_mean: float,
    debate_result: DebateResult | None,
    ref_weight: float,
    llm_weight: float,
) -> float:
    """Weighted blend of reference-class, CoT, and (optional) debate estimates.

    When debate is available the CoT weight is split: half to CoT mean and
    half to the debate-adjusted estimate, keeping weights summing to 1.0.
    """
    if debate_result is not None:
        # Remaining weight after reference class.
        remaining = 1.0 - ref_weight
        half = remaining / 2.0
        return ref_weight * ref_rate + half * cot_mean + half * debate_result.final_yes_prob
    else:
        # Normalise ref + llm (heuristic weight is applied externally by TopBetScorer).
        total = ref_weight + llm_weight
        if total == 0:
            return 0.5
        return (ref_weight * ref_rate + llm_weight * cot_mean) / total


def _build_context(market: dict) -> str:
    """Assemble a context string from market fields."""
    parts: list[str] = []
    if market.get("description"):
        parts.append(f"Description: {market['description']}")
    if market.get("category"):
        parts.append(f"Category: {market['category']}")
    if market.get("yes_price") is not None:
        parts.append(f"Current YES price: {market['yes_price']:.2%}")
    if market.get("volume_usd") is not None:
        parts.append(f"Volume: ${market['volume_usd']:,.0f}")
    if market.get("context"):
        parts.append(market["context"])
    return "\n".join(parts) if parts else "No additional context available."


def _build_reasoning(
    question: str,
    ref: ReferenceClassResult,
    cot: CoTResult,
    debate: DebateResult | None,
    final: float,
    confidence: float,
) -> str:
    lines = [
        f"Question: {question}",
        f"Reference class ({ref.reference_class_name}): base_rate={ref.base_rate_yes:.3f}, "
        f"confidence={ref.confidence:.2f}",
        f"CoT sampling: mean={cot.mean_yes_prob:.3f}, std_dev={cot.std_dev:.3f}, "
        f"samples={len(cot.samples)}",
    ]
    if debate:
        lines.append(f"Debate: judge_final={debate.final_yes_prob:.3f}, adjustment={debate.confidence_adjustment:+.3f}")
    lines += [
        f"Final YES probability: {final:.3f}",
        f"Overall confidence: {confidence:.3f}",
    ]
    return "\n".join(lines)


def _merge_config(user_cfg: dict) -> dict:
    """Deep-merge *user_cfg* over :data:`_DEFAULT_CONFIG`."""
    merged: dict = {}
    for key, default_val in _DEFAULT_CONFIG.items():
        if isinstance(default_val, dict):
            merged[key] = {**default_val, **user_cfg.get(key, {})}
        else:
            merged[key] = user_cfg.get(key, default_val)
    # Include any extra top-level keys from user config.
    for key in user_cfg:
        if key not in merged:
            merged[key] = user_cfg[key]
    return merged
