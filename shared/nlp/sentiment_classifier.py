"""
Sentiment classification using FinBERT.

Provides 5-class sentiment: Very Bullish, Bullish, Neutral, Bearish, Very Bearish.
FinBERT natively outputs 3 classes (positive, neutral, negative) -- we map to 5
classes using confidence thresholds.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

FINBERT_MODEL = os.getenv("FINBERT_MODEL", "ProsusAI/finbert")
DEVICE = os.getenv("SENTIMENT_DEVICE", "cpu")

HIGH_CONFIDENCE_THRESHOLD = 0.85
MODERATE_CONFIDENCE_THRESHOLD = 0.55


class SentimentLevel(str, Enum):
    VERY_BULLISH = "Very Bullish"
    BULLISH = "Bullish"
    NEUTRAL = "Neutral"
    BEARISH = "Bearish"
    VERY_BEARISH = "Very Bearish"


_NUMERIC_MAP = {
    SentimentLevel.VERY_BULLISH: 2,
    SentimentLevel.BULLISH: 1,
    SentimentLevel.NEUTRAL: 0,
    SentimentLevel.BEARISH: -1,
    SentimentLevel.VERY_BEARISH: -2,
}


@dataclass
class SentimentResult:
    level: SentimentLevel
    score: float  # -1.0 (most bearish) to 1.0 (most bullish)
    confidence: float  # 0.0 to 1.0
    raw_label: str  # original FinBERT label
    raw_scores: dict[str, float]  # positive/neutral/negative probabilities

    @property
    def numeric(self) -> int:
        return _NUMERIC_MAP[self.level]

    @property
    def is_bullish(self) -> bool:
        return self.level in (SentimentLevel.BULLISH, SentimentLevel.VERY_BULLISH)

    @property
    def is_bearish(self) -> bool:
        return self.level in (SentimentLevel.BEARISH, SentimentLevel.VERY_BEARISH)


class SentimentClassifier:
    """Classifies financial text sentiment using FinBERT with 5-class mapping."""

    def __init__(self, model_name: str = FINBERT_MODEL, device: str = DEVICE):
        self.model_name = model_name
        self.device = device
        self._pipeline = None

    def _get_pipeline(self):
        if self._pipeline is None:
            try:
                from transformers import pipeline
                self._pipeline = pipeline(
                    "sentiment-analysis",
                    model=self.model_name,
                    device=-1 if self.device == "cpu" else 0,
                    top_k=None,
                )
                logger.info("Loaded FinBERT model: %s", self.model_name)
            except ImportError:
                logger.error(
                    "transformers library not installed. "
                    "Install with: pip install transformers torch"
                )
                raise
            except Exception as e:
                logger.error("Failed to load FinBERT: %s", e)
                raise
        return self._pipeline

    def classify(self, text: str) -> SentimentResult:
        """Classify a single text and return 5-class sentiment."""
        pipe = self._get_pipeline()
        truncated = text[:512]
        outputs = pipe(truncated)

        scores_list = outputs[0] if isinstance(outputs[0], list) else outputs
        raw_scores = {item["label"]: item["score"] for item in scores_list}

        pos = raw_scores.get("positive", 0.0)
        neg = raw_scores.get("negative", 0.0)
        neu = raw_scores.get("neutral", 0.0)

        composite = pos - neg

        if pos > neg and pos > neu:
            if pos >= HIGH_CONFIDENCE_THRESHOLD:
                level = SentimentLevel.VERY_BULLISH
            elif pos >= MODERATE_CONFIDENCE_THRESHOLD:
                level = SentimentLevel.BULLISH
            else:
                level = SentimentLevel.NEUTRAL
        elif neg > pos and neg > neu:
            if neg >= HIGH_CONFIDENCE_THRESHOLD:
                level = SentimentLevel.VERY_BEARISH
            elif neg >= MODERATE_CONFIDENCE_THRESHOLD:
                level = SentimentLevel.BEARISH
            else:
                level = SentimentLevel.NEUTRAL
        else:
            level = SentimentLevel.NEUTRAL

        dominant_label = max(raw_scores, key=raw_scores.get)  # type: ignore[arg-type]
        confidence = raw_scores[dominant_label]

        return SentimentResult(
            level=level,
            score=round(composite, 4),
            confidence=round(confidence, 4),
            raw_label=dominant_label,
            raw_scores={k: round(v, 4) for k, v in raw_scores.items()},
        )

    def classify_batch(self, texts: list[str]) -> list[SentimentResult]:
        """Classify multiple texts efficiently."""
        return [self.classify(t) for t in texts]

    @staticmethod
    def aggregate_sentiment(results: list[SentimentResult]) -> SentimentResult | None:
        """Aggregate multiple sentiment results into a single composite."""
        if not results:
            return None

        avg_score = sum(r.score for r in results) / len(results)
        avg_confidence = sum(r.confidence for r in results) / len(results)

        if avg_score >= 0.5:
            level = SentimentLevel.VERY_BULLISH
        elif avg_score >= 0.15:
            level = SentimentLevel.BULLISH
        elif avg_score <= -0.5:
            level = SentimentLevel.VERY_BEARISH
        elif avg_score <= -0.15:
            level = SentimentLevel.BEARISH
        else:
            level = SentimentLevel.NEUTRAL

        avg_raw = {}
        for key in ("positive", "neutral", "negative"):
            vals = [r.raw_scores.get(key, 0.0) for r in results]
            avg_raw[key] = round(sum(vals) / len(vals), 4)

        return SentimentResult(
            level=level,
            score=round(avg_score, 4),
            confidence=round(avg_confidence, 4),
            raw_label=level.value,
            raw_scores=avg_raw,
        )
