# Skill: Knowledge Base Query

## Purpose
Query a structured knowledge base (docs, FAQs, strategy notes) to retrieve relevant information for decision support or user questions.

## Triggers
- When the agent needs to look up documentation or prior knowledge
- When user asks about strategy rules, risk limits, or procedures
- When validating actions against documented policies
- When answering "how does X work" or "what is the rule for Y"

## Inputs
- `query`: string — Natural language or keyword query
- `source`: string — "docs", "faq", "strategies", "all", or specific collection
- `top_k`: number — Max results to return (default: 5)
- `min_score`: number — Minimum relevance score 0–1 (default: 0.5)
- `filters`: object — Optional: category, date_range, tags

## Outputs
- `results`: object[] — Matched chunks with content, score, source
- `answer`: string — Optional synthesized answer if LLM summarization requested
- `metadata`: object — Query, source, result_count, latency_ms

## Steps
1. Resolve source; load or connect to knowledge base (vector DB, search index)
2. Embed or tokenize query for retrieval
3. Search/retrieve top_k chunks by similarity or keyword match
4. Filter by min_score and optional filters
5. Rank results by relevance
6. Optionally synthesize answer from top chunks via LLM
7. Return results with content, score, source path
8. Cache frequent queries with short TTL
9. Log queries for analytics

## Example
```
Input: query="What is the max position size for NVDA?", source="strategies", top_k=3
Output: {
  results: [{content: "Max position size for NVDA: 100 shares or 5% of portfolio", score: 0.92, source: "strategies/nvda_rules.md"}],
  answer: "Max position size for NVDA is 100 shares or 5% of portfolio, whichever is smaller.",
  metadata: {query: "max position size NVDA", source: "strategies", result_count: 1, latency_ms: 45}
}
```
