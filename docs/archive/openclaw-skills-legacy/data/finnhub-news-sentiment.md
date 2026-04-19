# Finnhub News & Sentiment

## Purpose
Fetch real-time financial news and sentiment scores from Finnhub for catalyst and narrative tracking.

## Category
data

## API Integration
- Provider: Finnhub; REST API; API key in query param `?token=`; 60 req/min (free tier); Free tier available

## Triggers
- When agent needs news or sentiment for a ticker
- When user requests news, headlines, or sentiment analysis
- When building catalyst-based signals or narrative decay
- When monitoring breaking news for positions

## Inputs
- `symbols`: string[] — Tickers to fetch news for
- `category`: string — "general", "forex", "crypto", "merger" (optional)
- `min_id`: number — Pagination; fetch news after this ID (optional)
- `from`: string — ISO date filter (optional)
- `to`: string — ISO date filter (optional)
- `limit`: number — Max articles (default: 25)

## Outputs
- `news`: object[] — Articles: headline, summary, source, url, datetime, related
- `sentiment`: object — Aggregate sentiment per symbol (if available)
- `metadata`: object — Source, fetched_at, rate_limit_remaining

## Steps
1. Call Finnhub /news endpoint with symbol and category
2. Add token query param
3. Respect 60 req/min; use 1s delay between bursts
4. Parse articles: headline, summary, source, url, datetime, related symbols
5. For sentiment: use /news-sentiment if available for symbol
6. Filter by from/to dates if provided
7. Limit results; paginate with min_id if needed
8. Return news array and metadata
9. Cache with 5m TTL for general news; 1m for breaking

## Example
```
Input: symbols=["AAPL","NVDA"], category="general", limit=10
Output: {
  news: [{headline:"Apple announces new AI features",summary:"...",source:"Reuters",url:"...",datetime:"2025-03-03T12:00:00Z",related:["AAPL"]}],
  sentiment: {AAPL: 0.65, NVDA: 0.72},
  metadata: {source:"finnhub", fetched_at:"2025-03-03T14:00:00Z"}
}
```

## Notes
- Free tier: 60 req/min; upgrade for higher limits
- Sentiment endpoint may have different availability
- News can be delayed; check provider SLA
