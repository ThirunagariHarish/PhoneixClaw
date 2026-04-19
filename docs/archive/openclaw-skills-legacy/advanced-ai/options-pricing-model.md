# Options Pricing Model

## Purpose
Price options using Black-Scholes or binomial tree models.

## Category
advanced-ai

## Triggers
- When valuing options for strategy
- When computing Greeks for hedging
- When user requests option price
- When backtesting options strategies

## Inputs
- `symbol`: string — Underlying ticker
- `strike`: number — Strike price
- `expiry`: string — Expiration date (ISO)
- `option_type`: string — "call" or "put"
- `spot`: number — Current underlying price
- `rate`: number — Risk-free rate (default: 0.05)
- `model`: string — "black_scholes", "binomial", "monte_carlo"
- `volatility`: number — Implied or historical vol (required)

## Outputs
- `price`: number — Option theoretical value
- `greeks`: object — Delta, gamma, theta, vega, rho
- `implied_vol`: number — IV if solving (optional)
- `metadata`: object — Model, inputs, timestamp

## Steps
1. Validate inputs (spot > 0, strike > 0, expiry > today)
2. Compute time to expiry in years
3. For Black-Scholes: apply closed-form formula
4. For binomial: build tree and back-propagate
5. Compute Greeks via finite difference or analytic
6. Return price, greeks, metadata

## Example
```
Input: symbol="AAPL", strike=180, expiry="2025-06-20", option_type="call", spot=175, volatility=0.25, model="black_scholes"
Output: {
  price: 8.42,
  greeks: {delta: 0.52, gamma: 0.03, theta: -0.12, vega: 0.18, rho: 0.05},
  metadata: {model: "black_scholes", spot: 175, vol: 0.25}
}
```

## Notes
- Assumes European exercise unless binomial with early exercise
- Dividend adjustment supported for Black-Scholes
- IV solver available for market price → vol
