# Fake News Verifier

## Purpose
Cross-reference headlines across multiple sources for verification and credibility scoring.

## Category
utility

## Triggers
- When user requests verification of a headline or news item
- When assessing credibility before acting on news catalyst
- When building trust score for news-driven signals
- When filtering low-quality or unverified headlines

## Inputs
- `headline`: string — Headline or claim to verify
- `symbol`: string — Optional related ticker for source filtering
- `sources`: string[] — Sources to check (default: Reuters, Bloomberg, AP, CNBC)
- `max_sources`: number — Max sources to query (default: 5)
- `include_sentiment`: boolean — Compare sentiment across sources (default: true)

## Outputs
- `verified`: boolean — True if corroborated by multiple reputable sources
- `corroboration_count`: number — Number of sources with matching story
- `sources_found`: object[] — [{source, url, headline_match, sentiment}]
- `credibility_score`: number — 0–1, aggregate credibility
- `discrepancy_alert`: boolean — True if sources conflict significantly
- `metadata`: object — headline_hash, computed_at

## Steps
1. Normalize headline; extract key entities (company, event type)
2. Query each source (RSS, API, or search) for matching stories
3. Match stories by entity overlap, timestamp, and semantic similarity
4. corroboration_count = sources with match above similarity threshold
5. verified = corroboration_count >= 2 and no major conflict
6. credibility_score: weight by source reputation (Reuters, AP high; blogs low)
7. discrepancy_alert: sentiment or fact conflict across sources
8. Return verified, corroboration_count, sources_found, credibility_score, discrepancy_alert, metadata
9. Cache by headline hash with 1h TTL

## Example
```
Input: headline="Apple announces new AI chip", symbol="AAPL"
Output: {
  verified: true,
  corroboration_count: 4,
  sources_found: [
    {source: "Reuters", url: "...", headline_match: 0.95, sentiment: "neutral"},
    {source: "Bloomberg", url: "...", headline_match: 0.92, sentiment: "neutral"}
  ],
  credibility_score: 0.92,
  discrepancy_alert: false,
  metadata: {computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Use marketaux-headlines, Finnhub, or custom news APIs
- Unverified headlines: reduce weight in news-catalyst-trade
- Consider NLP for semantic matching across sources
