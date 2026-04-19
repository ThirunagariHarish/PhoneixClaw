# Vanna & Charm Tracker

## Purpose
Track options Vanna (delta/vol sensitivity) and Charm (delta/time decay) second-order Greeks for dealer hedging and theta/vol impact.

## Category
analysis

## API Integration
- Consumes: Options chain and Greeks from options data provider; Requires Black-Scholes or BSM implementation; No direct API

## Triggers
- When agent needs Vanna or Charm Greeks
- When user requests second-order Greeks, dealer hedging, or theta/vol sensitivity
- When assessing options-driven flows from Greeks
- When building vol surface or decay models

## Inputs
- `options_chain`: object[] — Strikes with delta, gamma, vega, theta
- `underlying_price`: number — Current spot
- `iv_surface`: object — Implied vol by strike/expiry (optional)
- `compute_greeks`: boolean — Compute via BSM if not provided (default: true)

## Outputs
- `vanna`: object — Vanna per strike/expiry (dV/dσ or dΔ/dσ)
- `charm`: object — Charm per strike/expiry (dΔ/dt)
- `aggregate_vanna`: number — Net vanna exposure (dealer hedging direction)
- `aggregate_charm`: number — Net charm (theta decay pressure)
- `metadata`: object — Underlying, computed_at

## Steps
1. If options_chain lacks Vanna/Charm, compute via BSM (or finite difference)
2. Vanna = ∂Δ/∂σ ≈ vega * (d1/σ√T) or analytic formula
3. Charm = ∂Δ/∂t; negative for long options (delta decays)
4. Aggregate vanna across strikes: net long vanna = dealers buy vol when spot drops
5. Aggregate charm: net charm indicates theta decay pressure
6. Return vanna, charm, aggregates per strike/expiry
7. Cache with 5m TTL; Greeks change with spot/vol

## Example
```
Input: options_chain=[{strike:5900,delta:0.5,gamma:0.02,vega:50}], underlying_price=5910
Output: {
  vanna: {5900: 12.5, 5910: 8.2},
  charm: {5900: -0.015, 5910: -0.012},
  aggregate_vanna: 125000,
  aggregate_charm: -8500,
  metadata: {underlying:"SPX", computed_at:"2025-03-03T14:30:00Z"}
}
```

## Notes
- Vanna: spot down -> vol up -> long vol gains; dealers hedge by buying
- Charm: delta decays toward 0 (OTM) or 1 (ITM) as expiry approaches
- 0DTE has extreme charm; large daily rebalancing
