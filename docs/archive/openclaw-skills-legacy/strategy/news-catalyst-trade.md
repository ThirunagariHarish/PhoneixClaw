# News Catalyst Trade

## Purpose
Identify and trade on high-impact news catalysts with quantified sentiment and momentum.

## Category
strategy

## Triggers
- When news headline scores above impact threshold
- On earnings surprise or FDA decision
- On significant analyst upgrade/downgrade

## Inputs
- headline: News headline text (string)
- symbol: Affected ticker symbol (string)
- sentiment_score: Pre-computed sentiment score -1 to 1 (float)
- urgency: Time sensitivity — immediate, today, this_week (string)

## Outputs
- trade_signal: Directional signal — long, short, none (string)
- confidence: Signal confidence 0-1 (float)
- suggested_size: Position size as % of portfolio (float)
- time_horizon: Expected hold time (string)
- catalyst_type: Classification of the catalyst (string)

## Steps
1. Classify the news catalyst type (earnings, FDA, analyst, macro, geopolitical)
2. Score the expected price impact using historical catalyst analysis
3. Check if the stock has already moved significantly (avoid chasing)
4. Evaluate options IV to determine if event is priced in
5. Generate directional signal based on sentiment and catalyst type
6. Size position inversely to uncertainty
7. Set time-based exit (catalyst trades have defined durations)

## Example
"NVDA beats earnings by 20%, raises guidance" — long signal, 0.85 confidence, 2% portfolio size, hold 2-3 days for post-earnings drift.

## Notes
- Speed matters: catalyst trades lose edge quickly as market prices in information
- Be wary of "buy the rumor, sell the news" patterns
- Always check pre/post-market action before placing catalyst trades
