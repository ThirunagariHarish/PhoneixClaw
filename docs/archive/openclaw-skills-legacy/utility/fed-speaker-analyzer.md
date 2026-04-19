# Fed Speaker Analyzer

## Purpose
Analyze transcripts from Federal Reserve officials for tone and policy implications.

## Category
utility

## Triggers
- When user requests Fed speaker analysis
- When assessing hawkish/dovish shift from recent speeches
- When building macro regime or rate path expectations
- After FOMC meetings or major Fed speeches

## Inputs
- `transcript_source`: string — URL, file path, or "recent" for latest
- `speaker_filter`: string[] — Optional: Powell, Williams, etc. (default: all)
- `lookback_days`: number — Days to include (default: 7)
- `output_format`: string — "summary", "scores", "full" (default: "summary")
- `llm_provider`: string — Model for analysis (default: from config)

## Outputs
- `hawkish_score`: number — -1 to 1 (positive = hawkish)
- `dovish_score`: number — -1 to 1 (positive = dovish)
- `key_phrases`: string[] — Extracted policy-relevant phrases
- `rate_implication`: string — "hike_likely", "hold", "cut_likely", "uncertain"
- `summary`: string — Brief summary of tone and implications
- `metadata`: object — speakers, sources, computed_at

## Steps
1. Fetch transcripts from Fed website, Reuters, or provided source
2. Filter by speaker_filter and lookback_days
3. Chunk text for LLM; run sentiment/policy analysis
4. Extract hawkish/dovish keywords: "inflation", "patience", "data-dependent", etc.
5. Compute hawkish_score and dovish_score from phrase weights
6. rate_implication: map scores to hike/hold/cut/uncertain
7. Extract key_phrases with policy relevance
8. Generate summary if output_format includes it
9. Return hawkish_score, dovish_score, key_phrases, rate_implication, summary, metadata
10. Cache with 1h TTL (refresh after new speeches)

## Example
```
Input: transcript_source="recent", lookback_days=7
Output: {
  hawkish_score: 0.2,
  dovish_score: 0.6,
  key_phrases: ["data-dependent", "patience", "inflation easing"],
  rate_implication: "cut_likely",
  summary: "Fed officials emphasized data dependence; tone tilted dovish with inflation easing.",
  metadata: {speakers: ["Powell", "Williams"], computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Use macro-regime-detector for regime integration
- Fed website, Reuters, Bloomberg for transcripts
- LLM analysis; validate with human review for critical decisions
