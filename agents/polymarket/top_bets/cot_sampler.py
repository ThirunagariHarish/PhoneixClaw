"""Chain-of-Thought (CoT) self-consistency sampler for Prediction Markets (Phase 15.4).

Runs N parallel LLM calls, each asking for a step-by-step probability
estimate, then aggregates via trimmed mean to reduce outlier sensitivity.

Reference:
    docs/prd/pm-accuracy-cot-sampling.md  (F-ACC-2)
    docs/architecture/polymarket-phase15.md  § 9 (Scorer Chain)
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Regex that captures the *last* floating-point number in an LLM response.
_FLOAT_RE = re.compile(r"(\d+(?:\.\d+)?)")

# Minimum successful calls before we trust the aggregate; below this we
# return a uniform prior as graceful degradation.
_MIN_SUCCESSFUL_CALLS = 3


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CoTResult:
    """Aggregated output of :class:`CoTSampler`."""

    mean_yes_prob: float
    """Trimmed mean of individual YES probability estimates (0.0–1.0)."""

    std_dev: float
    """Standard deviation of all (untrimmed) samples — reflects disagreement."""

    samples: list[float]
    """All N raw probability samples (may be empty on full failure)."""

    reasoning_traces: list[str]
    """LLM response text for each sample (parallel to *samples*)."""


# ---------------------------------------------------------------------------
# Sampler
# ---------------------------------------------------------------------------


class CoTSampler:
    """Run N parallel LLM calls and aggregate via trimmed mean.

    Args:
        llm_client: Any object exposing ``async generate(prompt, **kw)``
            that returns an object with a ``.text`` attribute.
        config:     Scorer config dict (``llm`` sub-key expected).
    """

    _PROMPT_TEMPLATE = (
        "Given the following prediction market question and context, "
        "carefully reason step by step about what the probability of YES is. "
        "Think through the evidence, base rates, and any relevant information. "
        "At the end of your reasoning, write a single floating point number between "
        "0.0 and 1.0 representing the probability of YES.\n\n"
        "Question: {question}\n\n"
        "Context:\n{context}"
    )

    def __init__(self, llm_client: object, config: dict) -> None:
        self._llm = llm_client
        self._cfg = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def sample(self, question: str, context: str, n: int = 5) -> CoTResult:
        """Run *n* parallel LLM calls and return an aggregated probability.

        Args:
            question: The prediction market question text.
            context:  RAG-retrieved or heuristic context to guide reasoning.
            n:        Number of independent samples.  Defaults to 5.

        Returns:
            :class:`CoTResult` with trimmed mean, std_dev, raw samples, and
            reasoning traces.  If fewer than :data:`_MIN_SUCCESSFUL_CALLS`
            succeed, returns a uniform prior with ``std_dev=0.5``.
        """
        prompt = self._PROMPT_TEMPLATE.format(question=question, context=context)
        llm_cfg = self._cfg.get("llm", {})
        model = llm_cfg.get("model", None)
        temperature = llm_cfg.get("temperature", 0.7)
        max_tokens = llm_cfg.get("max_tokens", 1024)

        # Fire all N calls simultaneously.
        tasks = [
            self._single_call(prompt, model=model, temperature=temperature, max_tokens=max_tokens)
            for _ in range(n)
        ]
        raw_results: list[tuple[float | None, str]] = await asyncio.gather(*tasks, return_exceptions=False)

        # Separate successes from failures.
        samples: list[float] = []
        traces: list[str] = []
        for prob, trace in raw_results:
            if prob is not None:
                samples.append(prob)
                traces.append(trace)

        if len(samples) < _MIN_SUCCESSFUL_CALLS:
            logger.warning(
                "cot_sampler: only %d/%d calls succeeded — returning uniform prior",
                len(samples),
                n,
            )
            return CoTResult(mean_yes_prob=0.5, std_dev=0.5, samples=[], reasoning_traces=[])

        std_dev = _std_dev(samples)
        trimmed_mean = _trimmed_mean(samples)

        logger.debug(
            "cot_sampler: n=%d, trimmed_mean=%.3f, std_dev=%.3f, samples=%s",
            n,
            trimmed_mean,
            std_dev,
            samples,
        )
        return CoTResult(
            mean_yes_prob=trimmed_mean,
            std_dev=std_dev,
            samples=samples,
            reasoning_traces=traces,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _single_call(
        self,
        prompt: str,
        *,
        model: str | None,
        temperature: float,
        max_tokens: int,
    ) -> tuple[float | None, str]:
        """Execute one LLM call and parse the probability from the response.

        Returns:
            ``(probability, response_text)`` on success, or
            ``(None, "")`` on any exception.
        """
        try:
            kwargs: dict = {"temperature": temperature, "max_tokens": max_tokens}
            if model:
                kwargs["model"] = model
            response = await self._llm.generate(prompt, **kwargs)
            text: str = response.text if hasattr(response, "text") else str(response)
            prob = _parse_last_float(text)
            return (prob, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cot_sampler: LLM call failed: %s", exc)
            return (None, "")


# ---------------------------------------------------------------------------
# Pure math helpers (easy to unit-test in isolation)
# ---------------------------------------------------------------------------


def _parse_last_float(text: str) -> float | None:
    """Extract the *last* float from *text* and clamp it to [0, 1].

    Returns ``None`` if no float is found.
    """
    matches = _FLOAT_RE.findall(text)
    if not matches:
        return None
    try:
        value = float(matches[-1])
        return max(0.0, min(1.0, value))
    except ValueError:
        return None


def _trimmed_mean(samples: list[float]) -> float:
    """Return the trimmed mean, dropping min and max when len >= 5."""
    if len(samples) < 5:
        return sum(samples) / len(samples)
    sorted_s = sorted(samples)
    trimmed = sorted_s[1:-1]  # drop lowest and highest
    return sum(trimmed) / len(trimmed)


def _std_dev(samples: list[float]) -> float:
    """Population standard deviation of *samples*."""
    if len(samples) < 2:
        return 0.0
    mean = sum(samples) / len(samples)
    variance = sum((x - mean) ** 2 for x in samples) / len(samples)
    return math.sqrt(variance)
