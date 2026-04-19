# Symbol Resolver

## Purpose
Resolve ticker symbols across exchanges and asset types (stocks, options, crypto, futures).

## Category
utility

## Triggers
- When symbol format differs between systems
- When resolving options symbols (OCC format)
- When mapping crypto tickers across exchanges
- When user provides ambiguous symbol

## Inputs
- `symbol`: string — Input symbol or identifier
- `from_format`: string — "ticker", "cusip", "isin", "occ", "crypto"
- `to_format`: string — Desired output format
- `exchange`: string — Target exchange (optional)
- `asset_type`: string — "stock", "option", "crypto", "future"

## Outputs
- `resolved`: object — Resolved symbol(s) in requested format
- `canonical`: string — Canonical ticker for internal use
- `metadata`: object — Exchange, asset type, source
- `alternatives`: object[] — Other valid representations

## Steps
1. Parse input symbol and detect format
2. Look up in symbol mapping (DB or config)
3. Resolve to target format and exchange
4. Return canonical ticker for internal consistency
5. Include alternatives if multiple valid forms exist
6. Cache resolution for repeated lookups

## Example
```
Input: symbol="AAPL250117C00180000", from_format="occ", to_format="ticker", asset_type="option"
Output: {
  resolved: {ticker: "AAPL", strike: 180, expiry: "2025-01-17", type: "call"},
  canonical: "AAPL250117C00180000",
  metadata: {asset_type: "option", exchange: "OPRA"},
  alternatives: ["AAPL Jan 17 2025 180 Call"]
}
```

## Notes
- OCC format: underlying + expiry + type + strike
- Crypto may have different tickers per exchange (BTC vs XBT)
- Futures use contract month codes
