# Geopolitical Risk Scraper

## Purpose
Monitor keywords like "War", "Sanctions", "Embargo" across news to flag geopolitical risk events.

## Category
advanced-ai

## Triggers
- When user requests geopolitical risk assessment
- When building risk-off or defensive positioning signals
- Periodically for risk dashboard (e.g., hourly scan)
- When assessing macro tail risks for portfolio

## Inputs
- `keywords`: string[] — Risk keywords (default: ["War", "Sanctions", "Embargo", "Military", "Conflict"])
- `sources`: string[] — News sources to scrape (default: Reuters, AP, BBC, FT)
- `lookback_hours`: number — Hours to scan (default: 24)
- `regions`: string[] — Optional: filter by region (e.g., "Middle East", "Ukraine")
- `severity_threshold`: string — "high", "medium", "low", "all" (default: "medium")

## Outputs
- `events`: object[] — [{headline, source, url, severity, keywords_matched, timestamp}]
- `risk_level`: string — "elevated", "normal", "low" (aggregate)
- `event_count`: number — Count of matching events
- `affected_assets`: string[] — Symbols or asset classes mentioned (if detectable)
- `metadata`: object — keywords, lookback, computed_at

## Steps
1. Fetch headlines from sources over lookback_hours (RSS, API, or scrape)
2. Match against keywords (case-insensitive, phrase match)
3. Classify severity: "War", "Nuclear" = high; "Sanctions", "Embargo" = medium; "Tension" = low
4. Filter by severity_threshold and regions
5. risk_level: event_count and severity mix -> elevated/normal/low
6. Extract affected_assets from headline (e.g., oil, Russia ETFs) via NER or keyword map
7. Return events, risk_level, event_count, affected_assets, metadata
8. Cache with 1h TTL; support webhook for real-time alerts

## Example
```
Input: keywords=["Sanctions", "Embargo"], lookback_hours=24
Output: {
  events: [
    {headline: "New sanctions on oil exports", source: "Reuters", url: "...", severity: "medium", keywords_matched: ["Sanctions"], timestamp: "2025-03-03T12:00:00Z"}
  ],
  risk_level: "elevated",
  event_count: 3,
  affected_assets: ["USO", "XLE"],
  metadata: {keywords: ["Sanctions", "Embargo"], lookback: 24, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Use marketaux-headlines, news APIs, or custom scrapers
- Integrate with macro-regime-detector for regime shifts
- High risk_level can trigger drawdown-recovery-mode or reduce exposure
