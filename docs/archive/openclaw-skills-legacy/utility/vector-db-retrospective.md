# Vector DB Retrospective

## Purpose
Agent reviews past 100 trades from vector DB for failure patterns and recurring mistakes.

## Category
utility

## Triggers
- On schedule (e.g., end-of-day or weekly)
- After drawdown exceeds threshold
- When user requests retrospective analysis
- When self-updating-prompt needs performance feedback

## Inputs
- `vector_db`: object — Connection to vector store (Pinecone, Qdrant, etc.)
- `collection`: string — Trade/decision collection name
- `n_trades`: number — Number of past trades to retrieve (default: 100)
- `filter`: object — Optional; symbol, date_range, outcome (win/loss)
- `embedding_model`: string — Model for query embedding (default: same as ingestion)

## Outputs
- `failure_patterns`: object[] — [{pattern, frequency, example_trades, recommendation}]
- `recurring_mistakes`: string[] — Human-readable list of repeated errors
- `improvement_suggestions`: string[] — Actionable changes to prompts or rules
- `summary`: string — Executive summary for logs or reports
- `metadata`: object — n_analyzed, date_range, vector_db_query_time_ms

## Steps
1. Build query: embed "failed trades, losing trades, mistakes, poor exits"
2. Query vector DB for top-n similar trades; optionally filter by outcome
3. Cluster or group by common themes (overtrading, late exits, wrong regime)
4. Extract failure_patterns with frequency and example trade IDs
5. Generate recurring_mistakes and improvement_suggestions via LLM or rules
6. Return failure_patterns, recurring_mistakes, improvement_suggestions, summary, metadata
7. Optionally feed into self-updating-prompt or post-trade-retrospective

## Example
```
Input: vector_db=client, collection="trades", n_trades=100, filter={outcome:"loss"}
Output: {
  failure_patterns: [{pattern: "late_exit_after_reversal", frequency: 12, example_trades: ["T1","T2"], recommendation: "Tighten trailing stop"}],
  recurring_mistakes: ["Holding through VIX spike", "Entering before earnings without edge"],
  improvement_suggestions: ["Add VIX filter to entries", "Pause 24h before earnings"],
  summary: "12/100 losses from late exits; 8 from earnings. Recommend VIX filter.",
  metadata: {n_analyzed: 100, date_range: "2025-02-01..2025-03-03", vector_db_query_time_ms: 45}
}
```

## Notes
- Ensure trades are embedded with rich context (market state, rationale, outcome)
- Vector DB must be populated by audit or trade logging pipeline
- Use with post-trade-retrospective for deeper per-trade analysis
