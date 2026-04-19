# SEC 13F Institutional Holdings

## Purpose
Fetch SEC EDGAR 13F filings for institutional holdings (hedge funds, asset managers) from the free SEC API.

## Category
data

## API Integration
- Provider: SEC EDGAR; REST API; No auth (User-Agent required); No rate limit (be respectful: 10 req/s max); Free

## Triggers
- When agent needs institutional holdings or 13F data
- When user requests 13F, institutional ownership, or whale positions
- When tracking hedge fund or asset manager positions
- When building smart-money flow signals

## Inputs
- `cik`: string[] — Central Index Key (e.g., 0001067983 for Berkshire)
- `company_name`: string — Search by name if CIK unknown (optional)
- `filing_type`: string — "13F-HR", "13F-HR/A" (default: both)
- `start`: string — ISO date for historical (optional)
- `end`: string — ISO date for historical (optional)
- `include_holdings`: boolean — Parse holding details (default: true)

## Outputs
- `filings`: object[] — Filing metadata: cik, form, date, holdings_count
- `holdings`: object[] — Per filing: issuer, cusip, value, shares, investment_discretion
- `metadata`: object — Source, fetched_at, cik_count

## Steps
1. Resolve company name to CIK via SEC company search if needed
2. Call SEC EDGAR full-text search or submissions endpoint
3. Filter by form type 13F-HR, 13F-HR/A
4. Fetch filing XML/HTML from accession number
5. Parse 13F XML: infoTable for holdings (issuer, cusip, value, shares)
6. Filter by start/end dates if provided
7. Return filings and holdings with metadata
8. Cache with 1d TTL; 13F filed quarterly
9. Respect 10 req/s; use User-Agent with contact info

## Example
```
Input: cik=["0001067983"], include_holdings=true
Output: {
  filings: [{cik:"0001067983",form:"13F-HR",date:"2025-02-14",holdings_count:45}],
  holdings: [{issuer:"APPLE INC",cusip:"037833100",value:125000000000,shares:915000000,investment_discretion:"SOLE"}],
  metadata: {source:"sec-edgar", fetched_at:"2025-03-03T14:00:00Z"}
}
```

## Notes
- 13F filed quarterly (45 days after quarter end)
- Holdings in USD value; shares as reported
- CIK lookup: SEC company search or company_tickers.json
