# HITL Discord Confirm

## Purpose
Human-in-the-loop: Discord confirm button for trades above size threshold before execution.

## Category
utility

## Triggers
- When proposed trade size exceeds configurable threshold (e.g., $10k notional)
- When agent confidence is below threshold (from agent-confidence-scorer)
- When symbol is on restricted list requiring manual approval
- When user enables HITL for all trades (conservative mode)

## Inputs
- `trade_proposal`: object — {symbol, side, size, notional_usd, rationale, agent_id}
- `threshold_notional`: number — Min notional to trigger HITL (default: 10000)
- `discord_webhook`: string — Webhook URL for Discord channel
- `timeout_seconds`: number — Max wait for confirmation (default: 120)
- `buttons`: string[] — ["CONFIRM", "REJECT", "MODIFY"] (default: CONFIRM, REJECT)

## Outputs
- `status`: string — "CONFIRMED" | "REJECTED" | "TIMEOUT" | "MODIFIED"
- `user_response`: string — Optional; reason or modification from user
- `modified_trade`: object — Optional; if MODIFIED, new proposal
- `response_time_seconds`: number — Time from send to user action

## Steps
1. Check if trade_proposal.notional_usd >= threshold_notional (or other rules)
2. Build Discord embed: symbol, side, size, notional, rationale, agent_id
3. Send to webhook with action buttons (Discord interactions API)
4. Wait for button click; poll or use Discord gateway for response
5. On CONFIRM: return status=CONFIRMED; downstream executes
6. On REJECT: return status=REJECTED; cancel proposal
7. On MODIFY: prompt for new size/price; return modified_trade
8. On timeout: return status=TIMEOUT; treat as REJECTED by default
9. Log response_time_seconds for latency monitoring

## Example
```
Input: trade_proposal={symbol:"AAPL",side:"BUY",size:500,notional_usd:87500,rationale:"breakout"}, threshold_notional=10000
Output: {
  status: "CONFIRMED",
  user_response: null,
  modified_trade: null,
  response_time_seconds: 23
}
```

## Notes
- Discord interactions require bot with applications.commands scope
- Consider fallback: SMS or email if Discord unavailable
- Integrate with agent-confidence-scorer: low confidence can also trigger HITL
