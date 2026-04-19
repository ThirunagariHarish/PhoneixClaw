# Natural Language Query

## Purpose
Query "Why did you take that trade?" and get plain-English explanation from agent decision history.

## Category
utility

## Triggers
- When user asks "Why did you take that trade?" or similar
- When reviewing trade in dashboard or audit
- When debugging unexpected agent behavior
- When compliance or audit requires human-readable rationale

## Inputs
- `query`: string — Natural language question (e.g., "Why did you buy AAPL at 2pm?")
- `trade_id`: string — Optional; specific trade to explain
- `agent_id`: string — Optional; filter by agent
- `date_range`: object — Optional; {start, end} if query is broad
- `context_window`: number — Max trades to consider (default: 50)

## Outputs
- `answer`: string — Plain-English explanation
- `supporting_trades`: object[] — Trades referenced in answer
- `confidence`: number — 0-100 how well query was answered
- `sources`: object[] — Decision logs, signals, or prompts used
- `follow_up_suggestions`: string[] — Suggested next questions

## Steps
1. Parse query; extract intent (why trade, what signal, when, symbol)
2. If trade_id: fetch that trade and its decision chain
3. If no trade_id: search decision logs by symbol, time, agent
4. Load context: signals, market state, agent rationale at decision time
5. Use LLM to generate plain-English answer from structured data
6. Include supporting_trades and sources for transparency
7. Generate follow_up_suggestions (e.g., "What was the stop loss?")
8. Return answer, supporting_trades, confidence, sources, follow_up_suggestions

## Example
```
Input: query="Why did you take that trade?", trade_id="T-20250303-001"
Output: {
  answer: "I bought 100 shares of AAPL at 2:14 PM because the stock broke above the 20-day high with above-average volume. RSI was 62, not overbought. My risk/reward was 1:2 with a stop at 178.50.",
  supporting_trades: [{trade_id: "T-20250303-001", symbol: "AAPL", side: "BUY", size: 100}],
  confidence: 92,
  sources: [{type: "decision_log", id: "D-001"}, {type: "signal", id: "S-breakout"}],
  follow_up_suggestions: ["What was the exit plan?", "Did you use a trailing stop?"]
}
```

## Notes
- Integrate with audit-log-pdf and vector-db-retrospective for rich context
- Ensure PII and internal keys are redacted in answer
- Use with agent-confidence-scorer data if available
