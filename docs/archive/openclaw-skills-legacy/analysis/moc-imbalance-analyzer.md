# MOC Imbalance Analyzer

## Purpose
Analyze Market-on-Close (MOC) imbalance data for end-of-day trading signals and imbalance-based entry/exit.

## Category
analysis

## API Integration
- Consumes: cboe-moc-imbalance data; No direct API; Processes MOC feed output

## Triggers
- When agent needs MOC imbalance analysis for EOD
- When user requests imbalance signals, MOC analysis, or close auction
- When building EOD trading or closing-bell strategies
- When assessing buy/sell pressure for final minutes

## Inputs
- `imbalances`: object[] — From cboe-moc-imbalance: symbol, buy_imbalance, sell_imbalance, net
- `threshold_pct`: number — Min imbalance % to flag (default: 5)
- `min_volume`: number — Min net shares to consider (optional)
- `universe`: string[] — Symbols to rank (optional)
- `historical_imbalances`: object[] — Prior days for comparison (optional)

## Outputs
- `signals`: object[] — Per symbol: symbol, net, imbalance_pct, signal (buy/sell/neutral)
- `ranked`: object[] — Sorted by |imbalance| for top opportunities
- `aggregate_signal`: string — "buy_heavy", "sell_heavy", "balanced"
- `divergence_alerts`: object[] — Symbols with unusual vs historical (optional)
- `metadata`: object — Threshold, computed_at, source

## Steps
1. Parse imbalances from cboe-moc-imbalance
2. Compute imbalance_pct = net / (buy + sell) * 100
3. Filter by threshold_pct and min_volume
4. Assign signal: buy (net > 0), sell (net < 0), neutral
5. Rank by absolute imbalance for top opportunities
6. Aggregate: sum net across universe -> aggregate_signal
7. If historical: compare to prior days for divergence
8. Return signals, ranked, aggregate_signal, metadata
9. Cache until next MOC release (daily)

## Example
```
Input: imbalances=[{symbol:"AAPL",buy:125000,sell:98000,net:27000}], threshold_pct=5
Output: {
  signals: [{symbol:"AAPL",net:27000,imbalance_pct:12.1,signal:"buy"}],
  ranked: [{symbol:"AAPL",net:27000,imbalance_pct:12.1}],
  aggregate_signal: "buy_heavy",
  divergence_alerts: [],
  metadata: {threshold:5, computed_at:"2025-03-03T20:51:00Z", source:"cboe"}
}
```

## Notes
- MOC published ~3:50 PM ET; analyze shortly after
- Large imbalance can move price 3:50-4:00 PM
- Historical comparison improves signal quality
