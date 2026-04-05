# Skill: Swing Trade Management

## Purpose
Handle positions that are held overnight or across multiple days. Swing trades have different risk management than intraday — they skip EOD auto-close and use wider stops.

## Detection

A position is marked as a swing trade if:
1. The analyst's backtest profile has `is_swing_trader: true`, OR
2. The analyst's typical hold time > 24 hours, OR
3. The user explicitly labels a trade as "swing" via chat

## Overnight Risk Management

### Before Market Close (3:30 PM ET)
- For each swing position, evaluate overnight risk:
  - If unrealised P&L > +5%: hold full position
  - If unrealised P&L between 0% and +5%: reduce position by 30%
  - If unrealised P&L < 0%: consider closing (run TA for confirmation)

### Next Day (at Market Open 9:30 AM ET)
- Check for overnight gap:
  - If gap against position > 2%: close immediately
  - If gap in favour of position: hold and adjust trailing stop
- Re-run pre-market analysis to update mode for the new day

## Stop-Loss for Swing Trades

- Wider stops than intraday: 2x ATR or 20% (whichever is wider)
- Trailing stop: 60% of max profit (looser than intraday's 70%)
- Time-based stop: if position is flat (< 2% move) after 3 days, close and move on

## Position Sizing

- Swing positions use 60% of normal position size to account for overnight gap risk
- Max 2 concurrent swing positions regardless of mode
