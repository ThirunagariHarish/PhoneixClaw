"""TopBetScorer — heuristic pre-filter + LLM scorer orchestrator (Phase 15.4).

Two-stage pipeline:
  1. Heuristic score: fast, free, eliminates low-quality candidates.
  2. LLM score: expensive, runs only on the top ``debate_top_k`` markets.
  3. Debate: even more expensive, runs only on the top-5 LLM results.

Reference:
    docs/architecture/polymarket-phase15.md  § 9 (Scorer Chain)
    docs/prd/polymarket-phase15.md           F15-F
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from agents.polymarket.data.embedding_store import EmbeddingStore
from agents.polymarket.top_bets.llm_scorer import LLMScorer, LLMScorerResult

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"

# Number of top LLM-scored markets to run debate on (cost optimisation).
_DEBATE_TOP_N = 5

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
class ScoredMarket:
    """A market with its full scoring result."""

    market: dict
    """Original market dict."""

    heuristic_score: float
    """Quick pre-filter score (0.0–1.0)."""

    llm_result: LLMScorerResult
    """Full LLM scorer output including debate if run."""

    final_score: float
    """Blended final score: heuristic_weight * heuristic + (1 - heuristic_weight) * llm."""


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class TopBetScorer:
    """Orchestrate heuristic pre-filter, LLM scoring, and debate for a batch of markets.

    Args:
        db_session:   Active async DB session (used internally by EmbeddingStore).
        llm_client:   Injected LLM client.
        config_path:  Path to ``config.yaml``; falls back to defaults if not found.
    """

    def __init__(
        self,
        db_session: AsyncSession,
        llm_client: Any,
        config_path: str | None = None,
    ) -> None:
        self._db = db_session
        self._llm = llm_client
        self._cfg = _load_config(config_path)
        self._embedding_store = EmbeddingStore(db_session=db_session)
        self._llm_scorer = LLMScorer(self._embedding_store, llm_client, self._cfg)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def score_batch(self, markets: list[dict], top_k: int = 20) -> list[ScoredMarket]:
        """Score a batch of markets through the full pipeline.

        Steps:
        1. Heuristic pre-filter — keep top ``top_k`` by heuristic score.
        2. LLM scorer — run on all ``top_k`` in parallel.
        3. Debate — run only on the top-:data:`_DEBATE_TOP_N` by LLM confidence.
        4. Return sorted list (highest final_score first).

        Args:
            markets: List of market dicts (each must have at least ``question``).
            top_k:   Maximum markets to pass to the LLM stage.

        Returns:
            List of :class:`ScoredMarket` sorted by ``final_score`` descending.
        """
        scorer_cfg = self._cfg.get("scorer", {})
        debate_top_k: int = scorer_cfg.get("debate_top_k", 20)
        effective_top_k = min(top_k, debate_top_k)
        heuristic_weight: float = scorer_cfg.get("heuristic_weight", 0.2)

        # --- Stage 1: Heuristic filter ---
        heuristic_pairs = [(m, await self._heuristic_score(m)) for m in markets]
        heuristic_pairs.sort(key=lambda x: x[1], reverse=True)
        candidates = heuristic_pairs[:effective_top_k]

        if not candidates:
            return []

        # --- Stage 2: LLM scoring (parallel, no debate yet) ---
        llm_tasks = [self._llm_scorer.score_market(m, run_debate=False) for m, _ in candidates]
        llm_results: list[LLMScorerResult] = await asyncio.gather(*llm_tasks)

        # Build intermediate ScoredMarket list (no debate yet).
        intermediate: list[ScoredMarket] = []
        for (market, h_score), llm_res in zip(candidates, llm_results):
            fs = _blend_final(h_score, llm_res.yes_probability, heuristic_weight)
            intermediate.append(
                ScoredMarket(market=market, heuristic_score=h_score, llm_result=llm_res, final_score=fs)
            )

        # Sort by LLM confidence to pick best debate candidates.
        intermediate.sort(key=lambda s: s.llm_result.confidence, reverse=True)

        # --- Stage 3: Debate on top-5 ---
        debate_candidates = intermediate[:_DEBATE_TOP_N]
        non_debate = intermediate[_DEBATE_TOP_N:]

        debate_tasks = [
            self._llm_scorer.score_market(sm.market, run_debate=True) for sm in debate_candidates
        ]
        debate_results: list[LLMScorerResult] = await asyncio.gather(*debate_tasks)

        # Replace llm_result with debate-augmented version.
        final_list: list[ScoredMarket] = []
        for sm, debate_res in zip(debate_candidates, debate_results):
            fs = _blend_final(sm.heuristic_score, debate_res.yes_probability, heuristic_weight)
            final_list.append(
                ScoredMarket(
                    market=sm.market,
                    heuristic_score=sm.heuristic_score,
                    llm_result=debate_res,
                    final_score=fs,
                )
            )
        final_list.extend(non_debate)
        final_list.sort(key=lambda s: s.final_score, reverse=True)

        logger.info(
            "top_bet_scorer: input=%d, after_heuristic=%d, after_debate=%d",
            len(markets),
            len(candidates),
            len(debate_candidates),
        )
        return final_list

    # ------------------------------------------------------------------
    # Heuristic scorer
    # ------------------------------------------------------------------

    async def _heuristic_score(self, market: dict) -> float:
        """Compute a fast heuristic quality score (0.0–1.0) for one market.

        Three sub-signals, equal weight (1/3 each):

        * **Liquidity** – log-normalised volume; higher = better.
        * **Time horizon** – prefer 7–60 days; penalty outside that window.
        * **Price centrality** – prefer prices near 0.5 (most uncertain).

        Returns:
            Float in ``[0.0, 1.0]``.
        """
        liquidity = _liquidity_score(market.get("volume_usd", 0.0))
        time_horizon = _time_horizon_score(market.get("days_to_resolution", 30))
        centrality = _price_centrality_score(market.get("yes_price", 0.5))
        return (liquidity + time_horizon + centrality) / 3.0


# ---------------------------------------------------------------------------
# Heuristic sub-score functions (pure, easy to test)
# ---------------------------------------------------------------------------


def _liquidity_score(volume_usd: float) -> float:
    """Log-normalised volume score. $0 → 0.0; $1M → ~0.83; $10M → 1.0."""
    if volume_usd <= 0:
        return 0.0
    # log10($10M) = 7 as the normalisation ceiling.
    return min(1.0, math.log10(max(1.0, volume_usd)) / 7.0)


def _time_horizon_score(days: float) -> float:
    """Score days to resolution.

    Sweet spot: 7–60 days → 1.0.
    Penalty ramps for <7 days (too short, random) and >60 days (too far out).
    Below 1 day or above 180 days → 0.0.
    """
    if days < 1 or days > 180:
        return 0.0
    if 7 <= days <= 60:
        return 1.0
    if days < 7:
        return days / 7.0
    # days 60–180: linearly decay from 1.0 to 0.0
    return max(0.0, 1.0 - (days - 60) / 120.0)


def _price_centrality_score(yes_price: float) -> float:
    """Prefer markets where YES price is near 0.5 (maximum uncertainty).

    ``score = 1 - 2 * abs(yes_price - 0.5)``
    So 0.5 → 1.0; 0.0 or 1.0 → 0.0.
    """
    return max(0.0, 1.0 - 2.0 * abs(yes_price - 0.5))


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------


def _load_config(config_path: str | None) -> dict:
    """Load YAML config from *config_path*; fall back to defaults if missing."""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    if path.exists():
        try:
            with path.open() as fh:
                loaded = yaml.safe_load(fh) or {}
            # Deep merge over defaults.
            merged: dict = {}
            for key, default_val in _DEFAULT_CONFIG.items():
                if isinstance(default_val, dict):
                    merged[key] = {**default_val, **loaded.get(key, {})}
                else:
                    merged[key] = loaded.get(key, default_val)
            return merged
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not load config from %s: %s — using defaults", path, exc)
    return dict(_DEFAULT_CONFIG)


# ---------------------------------------------------------------------------
# Blend helper
# ---------------------------------------------------------------------------


def _blend_final(heuristic: float, llm_yes: float, heuristic_weight: float) -> float:
    """Combine heuristic and LLM signals into a single final score."""
    llm_weight = 1.0 - heuristic_weight
    return heuristic_weight * heuristic + llm_weight * llm_yes
