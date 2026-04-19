# Monte Carlo Sim

## Purpose
Monte Carlo simulation for risk/returns, portfolio paths, and VaR estimation.

## Category
advanced-ai

## Triggers
- When estimating portfolio VaR or CVaR
- When projecting return distributions
- When stress-testing strategies
- When user requests simulation

## Inputs
- `n_simulations`: number — Number of paths (default: 10000)
- `horizon`: number — Time steps or days
- `returns`: number[] — Historical returns for calibration
- `model`: string — "gbm", "jump_diffusion", "historical"
- `initial_value`: number — Starting portfolio value
- `percentiles`: number[] — VaR percentiles (e.g., [0.01, 0.05])

## Outputs
- `paths`: number[][] — Simulated paths (optional, can be large)
- `final_values`: number[] — Terminal values
- `var`: object — VaR at requested percentiles
- `cvar`: object — CVaR (expected shortfall)
- `metadata`: object — n_sims, horizon, model

## Steps
1. Calibrate model (drift, vol) from returns
2. Generate random paths per model (GBM, jump-diffusion)
3. Aggregate final values
4. Compute VaR and CVaR at percentiles
5. Return paths (if requested), final_values, var, cvar
6. Optionally persist summary for reporting

## Example
```
Input: n_simulations=10000, horizon=252, returns=[...], model="gbm", initial_value=100000, percentiles=[0.01, 0.05]
Output: {
  final_values: [98500, 102300, ...],
  var: {0.01: -12000, 0.05: -8000},
  cvar: {0.01: -14500, 0.05: -9500},
  metadata: {n_simulations: 10000, horizon: 252, model: "gbm"}
}
```

## Notes
- GBM assumes log-normal returns
- Jump-diffusion for fat tails
- Paths omitted by default to save memory
