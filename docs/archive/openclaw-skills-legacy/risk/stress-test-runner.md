# Stress Test Runner

## Purpose
Run stress test scenarios on portfolio (e.g., market crash, sector shock, volatility spike) to estimate potential losses under adverse conditions.

## Category
risk

## Triggers
- When the agent needs to stress test portfolio
- When user requests stress test or scenario analysis
- When evaluating portfolio resilience to shocks
- When risk review or regulatory reporting requires scenario analysis

## Inputs
- `positions`: object[] — Positions: symbol, quantity, market_value, beta, sector
- `account_value`: number — Total equity
- `scenarios`: object[] — [{name, type, params}] e.g., {name: "market_crash", type: "benchmark_drop", params: {pct: -10}}
- `scenario_types`: string[] — "benchmark_drop", "sector_shock", "vol_spike", "rate_shock", "custom"
- `benchmark`: string — For benchmark_drop (default: "SPY")

## Outputs
- `results`: object[] — Per-scenario: {name, loss_dollar, loss_pct, positions_affected}
- `worst_scenario`: string — Scenario with largest loss
- `max_loss_dollar`: number — Largest loss across scenarios
- `metadata`: object — Scenarios_count, computed_at

## Steps
1. Validate positions and scenarios
2. For benchmark_drop: apply -beta * benchmark_drop_pct to each position; sum losses
3. For sector_shock: apply sector-specific drop to positions in that sector
4. For vol_spike: use vega or gamma to estimate options impact; adjust equity delta
5. For rate_shock: use duration or rho for fixed income; adjust equity via discount rate
6. For custom: apply user-defined shocks to symbols or sectors
7. Compute loss_dollar and loss_pct per scenario
8. Identify worst_scenario and max_loss_dollar
9. Return results, worst_scenario, max_loss_dollar, metadata
10. Compare to risk limits; flag if any scenario exceeds tolerance

## Example
```
Input: positions=[...], account_value=100000, scenarios=[{name: "market_crash", type: "benchmark_drop", params: {pct: -10}}, {name: "tech_selloff", type: "sector_shock", params: {sector: "XLK", pct: -15}}]
Output: {
  results: [
    {name: "market_crash", loss_dollar: -11500, loss_pct: -11.5, positions_affected: 5},
    {name: "tech_selloff", loss_dollar: -8200, loss_pct: -8.2, positions_affected: 3}
  ],
  worst_scenario: "market_crash",
  max_loss_dollar: -11500,
  metadata: {scenarios_count: 2, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Stress tests are hypothetical; actual losses may differ
- Use beta for equity; include options Greeks for options positions
- Consider correlation breakdown in stress (correlations often rise in crashes)
