# Skill: Pre-Market Analysis

## Purpose
Before market open each day, analyse overnight developments and market conditions to set the agent's operating mode (aggressive or conservative) and generate a market context summary.

## Trigger
Runs automatically at 9:00 AM ET, 30 minutes before market open.

## Data Sources

| Data | Source | Free? |
|------|--------|-------|
| Overnight futures (ES, NQ) | `yfinance` (ES=F, NQ=F) | Yes |
| VIX level and term structure | `yfinance` (^VIX, ^VIX9D) | Yes |
| Economic calendar | `pandas_datareader` / `econdb` | Yes |
| Sector ETFs | `yfinance` (XLF, XLK, XLE, etc.) | Yes |
| Pre-market movers | `yfinance` after 4 AM | Yes |

## Analysis Steps

1. **Futures Direction**: check ES and NQ pre-market price vs previous close
   - Green (> +0.3%): bullish bias
   - Red (< -0.3%): bearish bias
   - Flat: neutral

2. **VIX Analysis**:
   - VIX < 15: low volatility → wider entries, more trades (aggressive OK)
   - VIX 15-25: normal → balanced approach
   - VIX > 25: high volatility → tighter stops, fewer trades (conservative)
   - VIX term structure inverted (VIX > VIX9D): fear elevated → conservative

3. **Economic Calendar**: check for high-impact events today
   - FOMC, CPI, NFP, GDP → reduce position sizes or wait until after release
   - No major events → normal trading

4. **Sector Rotation**: compare sector ETF pre-market moves
   - If defensive sectors (XLU, XLP) outperforming: risk-off → conservative
   - If growth sectors (XLK, XLY) outperforming: risk-on → aggressive OK

## Output

Write `market_context.json`:
```json
{
  "date": "2026-04-03",
  "overall_bias": "bullish",
  "volatility_regime": "normal",
  "vix": 18.5,
  "futures": { "ES": "+0.45%", "NQ": "+0.62%" },
  "key_events": ["FOMC minutes 2:00 PM"],
  "sector_leaders": ["XLK", "XLY"],
  "sector_laggards": ["XLE", "XLU"],
  "recommended_mode": "aggressive",
  "reasoning": "Green futures, VIX normal, growth sectors leading. FOMC minutes at 2 PM — consider reducing exposure before then."
}
```

## Mode Setting

Based on the analysis, set `current_mode` in config.json:
- If recommended_mode differs from current, update and log the change
- Report market context to Phoenix via `report_to_phoenix.py`
