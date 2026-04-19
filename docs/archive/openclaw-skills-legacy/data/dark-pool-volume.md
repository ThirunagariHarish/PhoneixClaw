# Dark Pool Volume

## Purpose
Fetch dark pool volume, block trades, and off-exchange activity for institutional flow and liquidity analysis.

## Category
data

## Triggers
- When agent needs dark pool or block trade data
- When user requests off-exchange volume, block trades, or dark pool activity
- When building flow-based signals from institutional prints
- When assessing true liquidity vs displayed exchange volume

## Inputs
- `symbols`: string[] — Tickers to look up (string[])
- `data_type`: string — "volume", "blocks", "ratio", "aggregate" (string)
- `start`: string — ISO date for historical (string, optional)
- `end`: string — ISO date for historical (string, optional)
- `min_block_size`: number — Min shares for block (number, optional)
- `provider`: string — "polygon", "finra", "quiver", or default (string)

## Outputs
- `dark_pool_volume`: object — Off-exchange volume per symbol (object)
- `block_trades`: object[] — Large prints with price, size, time (object[])
- `dark_ratio`: object — Dark pool % of total volume (object)
- `aggregate`: object — Total, exchange, off-exchange volume (object)
- `metadata`: object — Source, date range, symbol count (object)

## Steps
1. Resolve dark pool data provider (Polygon, FINRA ADF, Quiver)
2. Fetch consolidated tape or ADF volume for symbols
3. Parse exchange vs off-exchange (dark pool) volume
4. For blocks: filter trades >= min_block_size (e.g., 10k shares)
5. Compute dark_ratio = dark_volume / total_volume * 100
6. For historical: aggregate daily dark volume over start/end
7. Normalize: volume in shares, dark_ratio in %
8. Handle provider differences: some report ADF, others estimate dark
9. Cache with short TTL for intraday; daily for historical
10. Return structured output with metadata

## Example
```
Input: symbols=["AAPL","NVDA","TSLA"], data_type="ratio"
Output: {
  dark_pool_volume: {AAPL: 25000000, NVDA: 18000000, TSLA: 12000000},
  dark_ratio: {AAPL: 38.5, NVDA: 42.1, TSLA: 35.2},
  aggregate: {AAPL: {total: 65000000, dark: 25000000}},
  metadata: {date: "2025-03-03", source: "polygon"}
}
```

## Notes
- Dark pool definitions vary; ADF is regulatory, some include other OTC
- Block size threshold is provider-dependent (e.g., 10k for stocks)
- High dark ratio can indicate institutional accumulation/distribution
