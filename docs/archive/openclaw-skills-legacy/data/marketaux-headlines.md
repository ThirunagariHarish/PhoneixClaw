# Marketaux Financial Headlines

## Purpose
Fetch financial news headlines with entity tagging (tickers, companies) from Marketaux for targeted news monitoring.

## Category
data

## API Integration
- Provider: Marketaux; REST API; API key in query param `api_key=`; 100 req/day (free); Free tier

## Triggers
- When agent needs news with entity/ticker tagging
- When user requests headlines for specific tickers or topics
- When building news-based signals with entity extraction
- When free tier is preferred over paid Finnhub

## Inputs
- `symbols`: string[] — Tickers to filter (optional)
- `topics`: string[] — "earnings", "ipo", "mergers", "technology" (optional)
- `language`: string — "en" (default)
- `limit`: number — Max articles (default: 10; free tier limited)
- `published_after`: string — ISO datetime (optional)

## Outputs
- `headlines`: object[] — Articles: title, url, description, entities, published_at
- `entities`: object — Extracted tickers/companies per article
- `metadata`: object — Source, fetched_at, requests_remaining

## Steps
1. Call Marketaux /news/all endpoint with filters
2. Add api_key query param
3. Respect 100 req/day; track usage; fail gracefully when exceeded
4. Parse response: title, url, description, entities (tickers, companies)
5. Filter by symbols if provided (match entities)
6. Filter by published_after if provided
7. Limit results to conserve quota
8. Return headlines with entity tagging
9. Cache with 1h TTL to minimize API calls

## Example
```
Input: symbols=["NVDA"], topics=["technology"], limit=5
Output: {
  headlines: [{title:"NVIDIA unveils next-gen GPU",url:"...",description:"...",entities:["NVDA","NVIDIA"],published_at:"2025-03-03T11:00:00Z"}],
  entities: {0: ["NVDA","NVIDIA"]},
  metadata: {source:"marketaux", fetched_at:"2025-03-03T14:00:00Z", requests_remaining: 95}
}
```

## Notes
- 100 req/day free tier; use sparingly; cache aggressively
- Entity tagging enables precise ticker-filtered news
- Consider batch requests for multiple symbols in one call
