# Skill: Portfolio Risk Assessor

## Purpose
Assess overall portfolio risk metrics: VaR, beta, correlation exposure, and stress scenarios to ensure risk stays within tolerance.

## Triggers
- When the agent needs portfolio-level risk assessment
- When user requests portfolio risk or VaR
- When max-drawdown-monitor or position-exposure-checker need portfolio context
- When rebalancing or risk review is triggered

## Inputs
- `positions`: object[] — Current positions: symbol, quantity, entry, current_price, side
- `account_value`: number — Total equity
- `benchmark`: string — For beta calculation (default: "SPY")
- `confidence`: number — VaR confidence level (default: 0.95)
- `lookback_days`: number — For volatility/correlation (default: 60)

## Outputs
- `var_dollar`: number — Value at Risk in dollars
- `var_pct`: number — VaR as % of portfolio
- `beta`: number — Portfolio beta to benchmark
- `stress_scenarios`: object — Drawdown in -5%, -10% market scenarios
- `metadata`: object — Positions_count, computed_at

## Steps
1. Fetch returns for each position and benchmark via market-data-fetcher
2. Compute portfolio weights from position values / account_value
3. Compute portfolio returns: weighted sum of position returns
4. VaR: historical or parametric; at confidence level, var_dollar = percentile loss * account_value
5. Beta: covariance(portfolio_returns, benchmark_returns) / variance(benchmark_returns)
6. Stress scenarios: apply -5%, -10% to benchmark; project portfolio loss using beta
7. Optionally compute expected shortfall (CVaR) for tail risk
8. Return var_dollar, var_pct, beta, stress_scenarios, metadata
9. Compare to risk limits; flag if exceeded
10. Log assessment for monitoring

## Example
```
Input: positions=[...], account_value=100000, confidence=0.95
Output: {
  var_dollar: 3200,
  var_pct: 3.2,
  beta: 1.15,
  stress_scenarios: {"market_down_5pct": -5750, "market_down_10pct": -11500},
  metadata: {positions_count: 5, computed_at: "2025-03-03T15:00:00Z"}
}
```
