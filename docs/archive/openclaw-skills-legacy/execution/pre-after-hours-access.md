# Pre/After Hours Access

## Purpose
Execute trades during extended hours (4AM–8PM EST) when regular session is closed.

## Category
execution

## Triggers
- When user requests trade during pre-market (4AM–9:30AM EST) or after-hours (4PM–8PM EST)
- When news catalyst occurs outside regular session
- When strategy explicitly targets extended-hours moves (e.g., earnings gap)

## Inputs
- `intent`: object — {symbol, side, quantity, order_type, limit_price?}
- `session`: string — "pre", "after", "both" (default: "both")
- `allow_extended`: boolean — Enable extended hours (default: true)
- `timezone`: string — User timezone for display (default: "America/New_York")

## Outputs
- `accepted`: boolean — Whether order was accepted for extended session
- `session_type`: string — "pre", "after", "regular"
- `order_id`: string — Broker order ID
- `estimated_fill_window`: string — "pre", "regular", "after" when fill likely
- `metadata`: object — session, exchange_rules, timestamp

## Steps
1. Check current time vs EST session windows: pre 4AM–9:30AM, regular 9:30AM–4PM, after 4PM–8PM
2. Validate broker supports extended hours for account/symbol
3. If intent during pre/after: set order flag/extended-hours attribute per broker API
4. Submit order with extended-hours flag
5. Return accepted, session_type, order_id, estimated_fill_window, metadata
6. Monitor for fills; extended-hours fills may have wider spreads

## Example
```
Input: intent={symbol: "NVDA", side: "buy", quantity: 50, order_type: "limit", limit_price: 875}, session="pre"
Output: {
  accepted: true,
  session_type: "pre",
  order_id: "ord_ext_123",
  estimated_fill_window: "pre",
  metadata: {session: "pre", exchange_rules: "extended", timestamp: "2025-03-03T07:00:00Z"}
}
```

## Notes
- Liquidity is lower; wider spreads and slippage expected
- Not all symbols support extended hours; validate per ticker
- Integrate with market-clock-widget for session awareness
