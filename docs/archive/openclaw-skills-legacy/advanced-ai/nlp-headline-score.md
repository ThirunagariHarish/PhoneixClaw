# NLP Headline Score

## Purpose
Score news headlines for market impact using sentiment and entity extraction.

## Category
advanced-ai

## Triggers
- When processing news feed for trading signals
- When screening headlines for relevance
- When user requests headline sentiment
- When event-driven strategy needs news filter

## Inputs
- `headlines`: string[] — Raw headline text
- `symbols`: string[] — Symbols to score relevance for
- `model`: string — "sentiment", "impact", "relevance"
- `threshold`: number — Minimum score to return (default: 0.5)
- `include_entities`: boolean — Extract tickers/entities (default: true)

## Outputs
- `scores`: object[] — Per-headline scores and metadata
- `sentiment`: object — Aggregate sentiment (positive/negative/neutral)
- `entities`: object[] — Extracted symbols and entities
- `metadata`: object — Model, count, timestamp

## Steps
1. Preprocess headlines (lowercase, tokenize)
2. Run sentiment model (transformers, VADER, or custom)
3. Extract entities (tickers, companies) via NER
4. Score relevance to requested symbols
5. Filter by threshold
6. Return scores, sentiment, entities

## Example
```
Input: headlines=["AAPL announces record iPhone sales"], symbols=["AAPL"], model="impact"
Output: {
  scores: [{headline: "...", score: 0.85, sentiment: "positive"}],
  sentiment: {positive: 0.85, negative: 0.05, neutral: 0.10},
  entities: [{text: "AAPL", type: "TICKER"}],
  metadata: {model: "impact", count: 1}
}
```

## Notes
- Supports batch processing for efficiency
- Model can be local (transformers) or API (OpenAI)
- Entity extraction improves symbol matching
