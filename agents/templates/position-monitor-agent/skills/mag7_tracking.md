# MAG-7 Tracking Skill

## Why MAG-7 Matters
The MAG-7 (AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA) drive ~30% of S&P 500 weight. Their direction often leads or amplifies broader market moves. As a position monitor, you use MAG-7 as a market sentiment proxy.

## How to Use
Run `python tools/mag7_correlation.py --side {your_side} --output mag7.json` each cycle.

The output gives you:
- `avg_mag7_change_pct` — average daily change across MAG-7
- `direction` — bullish or bearish
- `mag7_changes` — per-stock changes
- `spy_change_pct`, `qqq_change_pct` — broader market proxies
- `exit_urgency` — added to your overall urgency score

## Interpretation
- **Long position + MAG-7 down >1%**: market sentiment shifting against you, urgency +20
- **Long position + QQQ down >1.5%**: tech-heavy selloff, urgency +10 more
- **Short position + MAG-7 up >1%**: market rallying against you, urgency +20
- **Long position + MAG-7 strong (avg >+1%)**: tailwinds, can be patient
- **Mixed MAG-7 (some up, some down)**: low urgency contribution

## Specific Stock Watches
If your position ticker is closely correlated to a MAG-7 stock, watch that one specifically:
- Tech stocks → AAPL, MSFT, NVDA
- Consumer → AMZN, TSLA
- Social/AdTech → META, GOOGL
- Semis → NVDA (and check SOXX too)

## Combining with Other Signals
MAG-7 urgency stacks with TA, Discord, and Risk signals. A long position with:
- MAG-7 selling (-20)
- RSI overbought (-20)
- Discord sell signal (-40)
- = Urgency 80 → FULL_EXIT immediately
