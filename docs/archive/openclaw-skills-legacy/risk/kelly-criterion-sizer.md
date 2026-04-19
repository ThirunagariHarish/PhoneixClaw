# Kelly Criterion Sizer

## Purpose
Optimize position size using Kelly Criterion based on win probability and payoff ratio for mathematically optimal growth.

## Category
risk

## Triggers
- When user requests Kelly-based sizing or "optimal bet size"
- When strategy provides win probability and avg win/loss
- Before placing trade to determine position size

## Inputs
- `win_probability`: number — Historical or estimated P(win) (0–1)
- `avg_win`: number — Average profit per winning trade ($ or %)
- `avg_loss`: number — Average loss per losing trade ($ or %)
- `payoff_ratio`: number — Optional: avg_win/avg_loss (overrides avg_win, avg_loss if both provided)
- `kelly_fraction`: number — Fraction of full Kelly to use (e.g., 0.5 = half-Kelly, default: 0.5)
- `account_equity`: number — Total equity for sizing
- `max_position_pct`: number — Cap position as % of equity (default: 0.2)

## Outputs
- `kelly_fraction_raw`: number — Full Kelly fraction (0–1)
- `recommended_fraction`: number — Kelly_fraction * kelly_fraction_raw
- `position_size`: number — Shares or $ to allocate
- `position_pct`: number — % of account
- `metadata`: object — win_probability, payoff_ratio, kelly_fraction

## Steps
1. Compute payoff ratio: b = avg_win / avg_loss (if not provided)
2. Kelly formula: f* = (p*b - q) / b, where p=win_probability, q=1-p
3. Clamp f* to [0, 1]; negative = no edge, skip trade
4. Apply kelly_fraction: f = kelly_fraction * f*
5. position_pct = min(f, max_position_pct)
6. position_size = account_equity * position_pct / price (or share count)
7. Return kelly_fraction_raw, recommended_fraction, position_size, position_pct, metadata

## Example
```
Input: win_probability=0.55, avg_win=200, avg_loss=150, kelly_fraction=0.5, account_equity=50000, max_position_pct=0.2
Output: {
  kelly_fraction_raw: 0.183,
  recommended_fraction: 0.092,
  position_size: 4600,
  position_pct: 0.092,
  metadata: {win_probability: 0.55, payoff_ratio: 1.33, kelly_fraction: 0.5}
}
```

## Notes
- Full Kelly is aggressive; half-Kelly or quarter-Kelly reduces variance
- Win probability and payoff must be estimated from backtest or historical stats
- Integrate with position-sizer for consistency across sizing methods
