# Greeks Calculator

## Purpose
Calculate options Greeks (delta, gamma, theta, vega, rho) for single options or option spreads to support hedging and risk management decisions.

## Category
analysis

## Triggers
- When the agent needs Greeks for an options position or proposed trade
- When user requests delta, gamma, theta, vega, or rho for a contract
- When building delta-neutral hedges or managing options exposure
- When evaluating option risk before entry or adjustment

## Inputs
- `symbol`: string — Underlying ticker (e.g., "SPY", "AAPL")
- `option_type`: string — "call" or "put"
- `strike`: number — Strike price
- `expiration`: string — Expiration date (YYYY-MM-DD)
- `underlying_price`: number — Current underlying price
- `iv`: number — Implied volatility (decimal, e.g., 0.25)
- `risk_free_rate`: number — Risk-free rate (default: 0.05)
- `days_to_exp`: number — Optional; days to expiration if not derived from expiration

## Outputs
- `delta`: number — Rate of change of option price vs underlying
- `gamma`: number — Rate of change of delta vs underlying
- `theta`: number — Time decay per day (dollars)
- `vega`: number — Sensitivity to 1% IV change
- `rho`: number — Sensitivity to 1% rate change
- `metadata`: object — Inputs, model used (e.g., Black-Scholes), computed_at

## Steps
1. Validate inputs: strike, expiration, underlying_price, iv
2. Compute days to expiration from expiration date
3. Apply Black-Scholes or binomial model for pricing
4. Compute delta: partial derivative of option value w.r.t. underlying
5. Compute gamma: partial derivative of delta w.r.t. underlying
6. Compute theta: partial derivative w.r.t. time (per day)
7. Compute vega: partial derivative w.r.t. IV (per 1% move)
8. Compute rho: partial derivative w.r.t. risk-free rate (per 1% move)
9. Return Greeks object and metadata
10. For spreads, sum Greeks across legs with appropriate signs

## Example
```
Input: symbol="SPY", option_type="call", strike=450, expiration="2025-03-21", underlying_price=448, iv=0.18
Output: {
  delta: 0.52, gamma: 0.042, theta: -0.12, vega: 0.28, rho: 0.08,
  metadata: {model: "black_scholes", computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Black-Scholes assumes European-style; use binomial for American options
- Greeks are per-contract; multiply by 100 for standard contracts
- IV is critical; use market IV if available from options-flow-analyzer
