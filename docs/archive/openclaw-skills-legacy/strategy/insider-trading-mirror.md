# Insider Trading Mirror

## Purpose
Mirror trades from Senator/CEO stock disclosures (Form 4) for potential alpha from informed flow.

## Category
strategy

## Triggers
- When new Form 4 filing is published (SEC EDGAR)
- When user requests insider activity scan
- When building conviction for existing position (insider buy = confirm)
- On schedule (e.g., daily scan of new filings)

## Inputs
- `symbol_filter`: string[] — Optional; limit to symbols (default: all)
- `filing_types`: string[] — ["4", "4/A"] for Form 4 (default)
- `insider_types`: string[] — ["CEO", "CFO", "Director", "10% Owner", "Senator"]
- `min_transaction_value`: number — Min $ value to consider (default: 50000)
- `transaction_type`: string — "P" (purchase) | "S" (sale) | "both" (default: "P" for buys)
- `lookback_days`: number — Days to scan back (default: 7)

## Outputs
- `signals`: object[] — [{symbol, insider, role, transaction_type, shares, value_usd, filing_date, signal}]
- `mirror_actions`: object[] — Suggested trades: BUY when insider bought, AVOID when sold
- `confidence`: number — 0-100 based on size, role, and timing
- `metadata`: object — n_filings, date_range, source

## Steps
1. Fetch Form 4 filings from SEC EDGAR (API or scrape) for lookback_days
2. Parse XML: transaction type (P/S), shares, price, insider name, role
3. Filter by insider_types, min_transaction_value, transaction_type
4. For purchases: signal=BUY_MIRROR; for sales: signal=AVOID or REDUCE
5. Score confidence: CEO/CFO > Director; larger size = higher
6. Return signals, mirror_actions, confidence, metadata
7. Downstream can size position by confidence or use as filter for other strategies

## Example
```
Input: symbol_filter=["AAPL","MSFT"], insider_types=["CEO","CFO"], transaction_type="P", lookback_days=7
Output: {
  signals: [{symbol: "AAPL", insider: "Tim Cook", role: "CEO", transaction_type: "P", shares: 5000, value_usd: 875000, filing_date: "2025-03-01", signal: "BUY_MIRROR"}],
  mirror_actions: [{symbol: "AAPL", action: "BUY", confidence: 82}],
  confidence: 82,
  metadata: {n_filings: 3, date_range: "2025-02-24..2025-03-03", source: "SEC EDGAR"}
}
```

## Notes
- Form 4 has 2-day delay; some insiders file late
- Senator disclosures (STOCK Act) in separate system; may need different source
- Not all insider buys are bullish; consider context (options exercise, etc.)
