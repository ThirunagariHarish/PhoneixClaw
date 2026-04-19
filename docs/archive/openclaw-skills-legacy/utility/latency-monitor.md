# Latency Monitor

## Purpose
Measure delay from signal generation to trade execution for performance tuning and SLA tracking.

## Category
utility

## Triggers
- On every trade execution (fill or reject)
- When user requests latency metrics or performance report
- When latency exceeds threshold (e.g., >500ms for scalping)
- When debugging slow execution or missed fills

## Inputs
- `signal_timestamp`: string — ISO timestamp when signal was generated
- `execution_timestamp`: string — ISO timestamp when order was sent/filled
- `fill_timestamp`: string — Optional; when fill confirmed (for full round-trip)
- `agent_id`: string — Agent that generated signal
- `symbol`: string — Instrument traded
- `stage`: string — "order_sent" | "fill_confirmed" | "rejected"

## Outputs
- `signal_to_order_ms`: number — Milliseconds from signal to order sent
- `signal_to_fill_ms`: number — Optional; full round-trip if fill_timestamp provided
- `p50_p95_p99`: object — Percentiles for recent window (configurable)
- `alert`: boolean — True if latency exceeds threshold
- `metadata`: object — agent_id, symbol, stage, sample_count

## Steps
1. Parse timestamps; compute signal_to_order_ms (and signal_to_fill_ms if fill present)
2. Append to rolling window (e.g., last 1000 executions)
3. Compute p50, p95, p99 from window
4. Compare to threshold (e.g., 500ms for scalping); set alert
5. Return latency metrics, percentiles, alert, metadata
6. Emit to metrics backend for dashboards

## Example
```
Input: signal_timestamp="2025-03-03T14:30:00.123Z", execution_timestamp="2025-03-03T14:30:00.456Z",
       agent_id="high-freq-scalper", symbol="SPY"
Output: {
  signal_to_order_ms: 333,
  signal_to_fill_ms: null,
  p50_p95_p99: {p50: 280, p95: 520, p99: 890},
  alert: false,
  metadata: {agent_id: "high-freq-scalper", symbol: "SPY", stage: "order_sent", sample_count: 847}
}
```

## Notes
- Use high-resolution timestamps; clock sync critical for distributed systems
- Scalping strategies should target <200ms; swing can tolerate seconds
- Integrate with sleep-mode-optimizer to avoid measuring during low-liquidity hours
