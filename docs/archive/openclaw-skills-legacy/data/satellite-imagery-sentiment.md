# Satellite Imagery Sentiment

## Purpose
Analyze satellite data (parking lots, oil tankers, shipping) for alternative data signals.

## Category
data

## Triggers
- When user requests alternative data analysis
- When building retail or commodity thesis (parking lot traffic, oil storage)
- For earnings or macro prediction (economic activity proxy)
- When integrating with fundamental or thematic strategies

## Inputs
- `data_source`: string — "Orbital Insight", "Planet", "custom" or API endpoint
- `indicator_type`: string — "parking_lots" | "oil_tankers" | "shipping" | "construction"
- `symbols`: string[] — Related tickers (e.g., WMT for retail, XOM for oil)
- `date_range`: object — {start: ISO date, end: ISO date}
- `granularity`: string — "daily" | "weekly" (default: weekly)
- `api_key`: string — Optional; for paid providers

## Outputs
- `sentiment_score`: number — -100 to 100 (bearish to bullish)
- `time_series`: object[] — [{date, value, change_pct}]
- `signals`: object[] — [{symbol, signal, confidence, rationale}]
- `metadata`: object — source, indicator_type, date_range, n_observations

## Steps
1. Connect to data_source; fetch indicator_type for date_range
2. For parking_lots: aggregate car count at retail locations; compare to prior period
3. For oil_tankers: count vessels, tonnage; infer storage or demand
4. For shipping: port activity, vessel movements
5. Normalize to sentiment_score; compute change_pct vs baseline
6. Map to symbols; generate signals (e.g., WMT up if parking lot traffic up)
7. Return sentiment_score, time_series, signals, metadata
8. Use with fundamental or thematic strategies for conviction

## Example
```
Input: data_source="Orbital Insight", indicator_type="parking_lots", symbols=["WMT","TGT"], date_range={start:"2025-02-01", end:"2025-03-03"}
Output: {
  sentiment_score: 15,
  time_series: [{date: "2025-03-01", value: 1.08, change_pct: 8}],
  signals: [{symbol: "WMT", signal: "BULLISH", confidence: 65, rationale: "Parking lot traffic +8% WoW"}],
  metadata: {source: "Orbital Insight", indicator_type: "parking_lots", date_range: "2025-02-01..2025-03-03", n_observations: 28}
}
```

## Notes
- Satellite data is expensive; cache aggressively
- Weather (clouds, snow) can affect quality; filter noisy days
- Correlate with earnings dates for retail; oil with inventory reports
