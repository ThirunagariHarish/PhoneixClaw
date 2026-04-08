"""Bull/Bear/Judge debate scorer for Prediction Markets (Phase 15.4).

Runs three sequential LLM calls — a Bull advocate, a Bear advocate, and an
impartial Judge — to stress-test a probability estimate and surface any
systematic bias missed by simple CoT sampling.

Reference:
    docs/prd/pm-accuracy-debate-pipeline.md  (F-ACC-1)
    docs/architecture/polymarket-phase15.md  § 9 (Scorer Chain)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_FLOAT_RE = re.compile(r"(\d+(?:\.\d+)?)")


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class DebateResult:
    """Output of the Bull/Bear/Judge debate pipeline."""

    final_yes_prob: float
    """Judge's final probability of YES (0.0–1.0)."""

    bull_argument: str
    """Text of the Bull's (YES) argument."""

    bear_argument: str
    """Text of the Bear's (NO) argument."""

    judge_reasoning: str
    """Judge's full reasoning text including the final probability."""

    confidence_adjustment: float
    """Delta between debate result and CoT estimate: ``final_yes_prob - cot_estimate``."""


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class DebateScorer:
    """Three-round adversarial debate to refine a probability estimate.

    The pipeline is strictly sequential:
    1. **Bull call** — strongest argument for YES.
    2. **Bear call** — strongest argument for NO (sees bull argument).
    3. **Judge call** — impartial adjudication; emits final probability.

    Args:
        llm_client: Any object exposing ``async generate(prompt, **kw)``
            with a ``.text`` attribute on the response.
        config:     Scorer config dict (``llm`` sub-key expected).
    """

    _BULL_PROMPT = (
        "You are a confident investment analyst. Make the strongest possible case "
        "for why the answer to the following prediction market question is YES.\n\n"
        "Question: {question}\n"
        "Current probability estimate: {cot_estimate:.0%}\n\n"
        "Context:\n{context}\n\n"
        "Present your most compelling arguments for YES."
    )

    _BEAR_PROMPT = (
        "You are a skeptical investment analyst. Make the strongest possible case "
        "for why the answer to the following prediction market question is NO.\n\n"
        "Question: {question}\n\n"
        "The bull argument says:\n{bull_argument}\n\n"
        "Context:\n{context}\n\n"
        "Rebut the bull's case and present your most compelling arguments for NO."
    )

    _JUDGE_PROMPT = (
        "You are an impartial judge evaluating a prediction market question.\n\n"
        "Question: {question}\n\n"
        "Bull argument (for YES):\n{bull_argument}\n\n"
        "Bear argument (for NO):\n{bear_argument}\n\n"
        "After carefully weighing both arguments, what is the probability that the "
        "answer is YES? Respond with a brief reasoning followed by a single floating "
        "point number between 0.0 and 1.0 on the last line."
    )

    def __init__(self, llm_client: object, config: dict) -> None:
        self._llm = llm_client
        self._cfg = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def score(self, question: str, context: str, cot_estimate: float) -> DebateResult:
        """Run the three-round debate and return the judge's verdict.

        Args:
            question:     The prediction market question text.
            context:      RAG-retrieved or heuristic context.
            cot_estimate: Current probability estimate from :class:`CoTSampler`.

        Returns:
            :class:`DebateResult` with the judge's final probability and all
            intermediate arguments.  On any LLM failure the judge falls back
            to returning *cot_estimate* unchanged.
        """
        llm_cfg = self._cfg.get("llm", {})
        model = llm_cfg.get("model", None)
        temperature = llm_cfg.get("temperature", 0.3)
        max_tokens = llm_cfg.get("max_tokens", 1024)

        # --- Round 1: Bull ---
        bull_prompt = self._BULL_PROMPT.format(
            question=question,
            cot_estimate=cot_estimate,
            context=context,
        )
        bull_text = await self._call(bull_prompt, model=model, temperature=temperature, max_tokens=max_tokens)
        logger.debug("debate: bull argument length=%d", len(bull_text))

        # --- Round 2: Bear (sees bull argument) ---
        bear_prompt = self._BEAR_PROMPT.format(
            question=question,
            bull_argument=bull_text,
            context=context,
        )
        bear_text = await self._call(bear_prompt, model=model, temperature=temperature, max_tokens=max_tokens)
        logger.debug("debate: bear argument length=%d", len(bear_text))

        # --- Round 3: Judge (sees both) ---
        judge_prompt = self._JUDGE_PROMPT.format(
            question=question,
            bull_argument=bull_text,
            bear_argument=bear_text,
        )
        judge_text = await self._call(judge_prompt, model=model, temperature=temperature, max_tokens=max_tokens)
        logger.debug("debate: judge response length=%d", len(judge_text))

        # Parse the judge's final probability.
        final_prob = _parse_last_float(judge_text)
        if final_prob is None:
            logger.warning("debate: could not parse float from judge response; falling back to cot_estimate")
            final_prob = cot_estimate

        adjustment = final_prob - cot_estimate
        logger.debug(
            "debate: cot_estimate=%.3f, judge=%.3f, adjustment=%.3f",
            cot_estimate,
            final_prob,
            adjustment,
        )
        return DebateResult(
            final_yes_prob=final_prob,
            bull_argument=bull_text,
            bear_argument=bear_text,
            judge_reasoning=judge_text,
            confidence_adjustment=adjustment,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _call(self, prompt: str, *, model: str | None, temperature: float, max_tokens: int) -> str:
        """Thin wrapper around the injected LLM client."""
        try:
            kwargs: dict = {"temperature": temperature, "max_tokens": max_tokens}
            if model:
                kwargs["model"] = model
            response = await self._llm.generate(prompt, **kwargs)
            return response.text if hasattr(response, "text") else str(response)
        except Exception as exc:  # noqa: BLE001
            logger.error("debate: LLM call failed: %s", exc)
            return ""


# ---------------------------------------------------------------------------
# Shared float parser (mirrors cot_sampler._parse_last_float)
# ---------------------------------------------------------------------------


def _parse_last_float(text: str) -> float | None:
    """Extract the *last* float from *text* and clamp it to [0, 1]."""
    matches = _FLOAT_RE.findall(text)
    if not matches:
        return None
    try:
        value = float(matches[-1])
        return max(0.0, min(1.0, value))
    except ValueError:
        return None
