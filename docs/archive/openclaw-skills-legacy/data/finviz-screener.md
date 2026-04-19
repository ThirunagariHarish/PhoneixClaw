# Finviz Stock Screener

## Purpose
Scrape Finviz stock screener for technical and fundamental filters (P/E, volume, SMA, sector) when free screening is needed.

## Category
data

## API Integration
- Provider: Finviz; Web scraping (no official API); No auth; Free; Respect robots.txt and rate limit (1 req/2s recommended)

## Triggers
- When agent needs stock screening with technical/fundamental filters
- When user requests screener results, stock filters, or scan
- When free data is preferred over paid screeners
- When building watchlists from criteria

## Inputs
- `filters`: object — Key-value: pe, eps_growth, volume, sma20, sma50, sector, etc.
- `screener`: string — "usa", "forex", "crypto", "commodity" (default: usa)
- `order`: string — Sort by: "ticker", "price", "change", "volume" (optional)
- `limit`: number — Max results (default: 100)

## Outputs
- `results`: object[] — Rows: ticker, company, sector, price, change, volume, pe, etc.
- `metadata`: object — Filters applied, result count, scraped_at

## Steps
1. Build Finviz URL with filter query params (e.g., ?v=111&f=pe_u20,ta_sma20_pa)
2. Fetch page with requests/httpx; use User-Agent
3. Parse HTML table; extract ticker, company, sector, price, change, volume, P/E
4. Respect 1 req/2s to avoid blocks
5. Paginate if limit > 20 (Finviz shows 20 per page)
6. Apply order/sort if specified
7. Return results array and metadata
8. Cache with 1h TTL; screening is batch operation

## Example
```
Input: filters={pe: "u20", volume: "o500000", sma20: "pa"}, order="volume", limit=50
Output: {
  results: [{ticker:"AAPL",company:"Apple",sector:"Technology",price:175.50,change:1.2,volume:52000000,pe:28.5}],
  metadata: {filters: {pe:"u20",volume:"o500000"}, result_count: 50, scraped_at:"2025-03-03T14:00:00Z"}
}
```

## Notes
- Scraping may break if Finviz changes layout; use robust selectors
- Filter keys: pe, eps_growth, volume, sma20, sma50, sector, industry
- Consider fallback to Polygon or other API if scraping fails
