# Skill: Sentiment Scorer

## Purpose
Score sentiment from text (headlines, posts, tweets) on a scale of -1 (bearish) to 1 (bullish) for use in sentiment-based signals and aggregation.

## Triggers
- When the agent needs to score text sentiment for trading
- When user requests sentiment analysis of news or social content
- When building sentiment pipelines (news, Reddit, Twitter)
- When aggregating sentiment across sources in social-sentiment-collector

## Inputs
- `text`: string — Single text to score (headline, post, tweet)
- `texts`: string[] — Batch of texts (optional; use instead of text)
- `model`: string — "vader", "finbert", "custom", or default
- `context`: object — Optional: symbol, source type for domain tuning

## Outputs
- `score`: number — Sentiment from -1 (bearish) to 1 (bullish)
- `label`: string — "bearish", "neutral", or "bullish"
- `confidence`: number — Model confidence (0-1) if available
- `batch_scores`: object[] — When texts provided, per-text scores

## Steps
1. Select model: VADER (fast, general), FinBERT (financial domain), or custom
2. Preprocess text: lowercase, remove URLs, handle emojis (map to sentiment or strip)
3. For single text: run model inference; get raw score (e.g., compound from VADER)
4. Normalize to -1..1: map model output to standard scale
5. Assign label: bearish (<-0.2), neutral (-0.2 to 0.2), bullish (>0.2)
6. If batch: process each text; return batch_scores array
7. Compute confidence from model output if available (e.g., softmax prob)
8. For financial context: optionally boost/reduce based on keywords (earnings, beat, miss)
9. Return score, label, confidence; for batch, return batch_scores with metadata
10. Cache results for identical text to avoid redundant inference

## Example
```
Input: text="NVIDIA beats Q4 estimates, raises guidance - stock surges"
Output: {score: 0.82, label: "bullish", confidence: 0.91}

Input: texts=["NVDA to the moon", "Sell everything"]
Output: {batch_scores: [{text: "NVDA to the moon", score: 0.75}, {text: "Sell everything", score: -0.88}]}
```
