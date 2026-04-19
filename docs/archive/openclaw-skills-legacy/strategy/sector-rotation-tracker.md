# Skill: Sector Rotation Tracker

## Purpose
Track relative performance of sectors/industries vs benchmark to identify rotation into or out of sectors for thematic or rotation strategies.

## Triggers
- When the agent needs sector rotation insights
- When user requests sector strength or rotation plays
- When building sector-based watchlists
- When validating thematic entry timing

## Inputs
- `sectors`: string[] — Sector ETFs or indices (e.g., ["XLK","XLF","XLE","XLV"])
- `benchmark`: string — Index for relative strength (default: "SPY")
- `period`: number — Lookback days (default: 20)
- `rank_by`: string — "return", "relative_strength", "momentum"
- `timeframe`: string — "1d"

## Outputs
- `ranked`: object[] — Sectors sorted by strength (strongest first)
- `relative_strength`: object — Per-sector return vs benchmark
- `rotation_signal`: object — "inflow", "outflow", "neutral" per sector
- `metadata`: object — Period, benchmark, scan time

## Steps
1. Fetch price data for sector ETFs and benchmark via market-data-fetcher
2. Compute period returns for each sector and benchmark
3. Relative strength = sector_return - benchmark_return
4. Rank sectors by chosen metric (return or relative strength)
5. Compare current rank to prior period rank for rotation signal
6. Inflow: rank improved; outflow: rank worsened; neutral: unchanged
7. Return ranked list, relative_strength, rotation_signal
8. Cache with daily TTL

## Example
```
Input: sectors=["XLK","XLF","XLE","XLV"], benchmark="SPY", period=20
Output: {
  ranked: [{sector: "XLK", return: 5.2, rel_strength: 2.1}, {sector: "XLV", return: 3.8, rel_strength: 0.7}],
  relative_strength: {XLK: 2.1, XLF: 0.2, XLE: -1.5, XLV: 0.7},
  rotation_signal: {XLK: "inflow", XLF: "neutral", XLE: "outflow", XLV: "inflow"},
  metadata: {period: 20, benchmark: "SPY", scanned_at: "2025-03-03T15:00:00Z"}
}
```
