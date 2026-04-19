# Trading Replay Commentary

## Purpose
Bot explains its thoughts during trade replay with AI commentary for education and audit.

## Category
utility

## Triggers
- When user replays historical trade or session
- When training or reviewing agent behavior
- When generating educational content from past trades
- When audit requires narrative explanation of decision sequence

## Inputs
- `trade_replay`: object — {trades: [...], market_data: [...], decision_logs: [...]}
- `replay_speed`: number — 1x, 2x, etc. (default: 1)
- `commentary_style`: string — "educational" | "audit" | "concise" (default: educational)
- `include_rationale`: boolean — Explain each decision (default: true)
- `llm_provider`: string — For generating commentary (default: gpt-4o)

## Outputs
- `commentary`: object[] — [{timestamp, event, explanation, decision_context}]
- `summary`: string — Executive summary of replay session
- `lessons_learned`: string[] — Key takeaways for improvement
- `timeline`: object[] — Synced timeline for playback UI
- `metadata`: object — n_trades, duration, commentary_tokens

## Steps
1. Load trade_replay; order events chronologically
2. For each decision point: extract context (price, indicators, position)
3. Use LLM to generate explanation: "At 2:14 PM, I bought because..."
4. Style: educational = detailed; audit = factual; concise = one-liner
5. Build commentary array with timestamp, event, explanation
6. Generate summary and lessons_learned from full replay
7. Build timeline for playback UI (sync with market_data)
8. Return commentary, summary, lessons_learned, timeline, metadata
9. Optionally export to video or PDF with audit-log-pdf

## Example
```
Input: trade_replay={trades: [{symbol:"AAPL",entry:"14:14",exit:"15:30"}], market_data:[...], decision_logs:[...]},
       commentary_style="educational"
Output: {
  commentary: [{timestamp: "14:14", event: "ENTRY", explanation: "I entered long AAPL as price broke the 20-day high with volume confirmation. RSI at 62 suggested room to run.", decision_context: {price: 178.50, rsi: 62}}],
  summary: "One trade: AAPL long from 14:14 to 15:30. +0.8% gain. Entry on breakout; exit on profit target.",
  lessons_learned: ["Breakout entries with volume work well in trending sessions", "Consider trailing stop earlier when momentum fades"],
  timeline: [{t: "14:14", type: "entry", ...}, {t: "15:30", type: "exit", ...}],
  metadata: {n_trades: 1, duration: "76m", commentary_tokens: 450}
}
```

## Notes
- Integrate with natural-language-query for "Why did you do X at time T?"
- Use with vector-db-retrospective for failure-pattern extraction
- Ensure commentary matches actual decision logs; no hallucination
