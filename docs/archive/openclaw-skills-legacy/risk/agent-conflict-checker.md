# Agent Conflict Checker

## Purpose
Prevent agents from hedging each other out (e.g., one long and one short same ticker).

## Category
risk

## Triggers
- Before any agent places a new order
- When multiple agents/strategies run concurrently
- When consolidating signals from agent ensemble

## Inputs
- `agent_positions`: object — {agent_id: [{symbol, side, quantity}]}
- `proposed_trade`: object — {agent_id, symbol, side, quantity}
- `conflict_rules`: object — {allow_hedge: false, allow_same_side: true}
- `resolution`: string — "block", "warn", "override" (default: block)

## Outputs
- `conflict_detected`: boolean — True if proposed trade conflicts with another agent
- `conflicting_agents`: string[] — Agent IDs with opposite position in same symbol
- `conflict_type`: string — "opposite_side", "over_hedge", or null
- `allowed`: boolean — Whether to proceed (depends on resolution)
- `metadata`: object — proposed_trade, agent_positions_summary

## Steps
1. For proposed_trade.symbol: gather all positions from other agents (exclude proposing agent)
2. Sum net position per symbol: long - short
3. If proposed_trade.side opposes net (e.g., net long, proposed sell): conflict_detected=true
4. conflict_type="opposite_side" if would create or increase hedge
5. If allow_hedge=false: allowed=false when conflict; else allowed=true with warn
6. If resolution="block": allowed=false; "warn": allowed=true, log; "override": allowed=true
7. Return conflict_detected, conflicting_agents, conflict_type, allowed, metadata

## Example
```
Input: agent_positions={agent_a: [{symbol: "AAPL", side: "long", quantity: 100}], agent_b: []}, proposed_trade={agent_id: "agent_b", symbol: "AAPL", side: "short", quantity: 50}
Output: {
  conflict_detected: true,
  conflicting_agents: ["agent_a"],
  conflict_type: "opposite_side",
  allowed: false,
  metadata: {proposed_trade: {...}, net_aapl: 100}
}
```

## Notes
- Run before order-placer; integrate with multi-agent orchestration
- Consider net exposure across agents; partial hedge may be intentional
- Log conflicts for strategy tuning and agent coordination
