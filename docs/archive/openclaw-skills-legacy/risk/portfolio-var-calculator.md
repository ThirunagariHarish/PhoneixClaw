# Portfolio VaR Calculator

## Purpose
Calculate Value at Risk (VaR) for portfolio at specified confidence level using historical, parametric, or Monte Carlo methods to quantify downside risk.

## Category
risk

## Triggers
- When the agent needs portfolio VaR for risk reporting
- When user requests VaR or value at risk
- When comparing portfolio risk to limits
- When stress-test-runner or portfolio-risk-assessor need VaR input

## Inputs
- `positions`: object[] — Positions: symbol, quantity, market_value, side
- `account_value`: number — Total equity
- `confidence`: number — Confidence level (default: 0.95 for 95% VaR)
- `method`: string — "historical", "parametric", "monte_carlo" (default: historical)
- `lookback_days`: number — Days for historical returns (default: 252)
- `horizon_days`: number — VaR horizon (default: 1)
- `returns_data`: object — Optional pre-fetched returns; if empty, fetch via market-data-fetcher

## Outputs
- `var_dollar`: number — VaR in dollars (max loss at confidence level)
- `var_pct`: number — VaR as % of portfolio
- `expected_shortfall`: number — Conditional VaR (expected loss beyond VaR) (optional)
- `method_used`: string — Method applied
- `metadata`: object — Confidence, lookback_days, horizon, computed_at

## Steps
1. Fetch returns for each position if not provided
2. Compute portfolio returns: weighted sum of position returns by market value
3. If method=historical: sort returns; VaR = percentile(1 - confidence) * account_value
4. If method=parametric: assume normal; VaR = -mean + z_score(confidence) * std * sqrt(horizon)
5. If method=monte_carlo: simulate N paths; VaR = percentile of simulated losses
6. Scale for horizon: multiply 1-day VaR by sqrt(horizon_days) for parametric
7. Compute expected_shortfall: mean of losses beyond VaR threshold (optional)
8. Return var_dollar, var_pct, expected_shortfall, method_used, metadata
9. Flag if VaR exceeds risk limits
10. Log for monitoring and reporting

## Example
```
Input: positions=[...], account_value=100000, confidence=0.95, method="historical", lookback_days=252
Output: {
  var_dollar: 3200,
  var_pct: 3.2,
  expected_shortfall: 4200,
  method_used: "historical",
  metadata: {confidence: 0.95, lookback_days: 252, horizon_days: 1, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Historical VaR assumes past distribution; may underestimate tail risk
- Parametric VaR underestimates fat tails; use Monte Carlo for complex portfolios
- VaR is a threshold, not expected loss; use expected shortfall for tail risk
