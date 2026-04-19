# Skill: Memory Compaction

## Purpose
Compact and prune agent memory (conversation history, context buffer) to stay within token limits while preserving critical information.

## Triggers
- When the agent's context window is approaching limit
- When user requests memory cleanup or summarization
- When switching tasks or starting a new session
- When long-running agent needs to free memory

## Inputs
- `memory_type`: string — "conversation", "context", "cache", or "all"
- `max_tokens`: number — Target max tokens after compaction (optional)
- `preserve`: string[] — Keys or patterns to never prune (e.g., ["positions", "config"])
- `strategy`: string — "summarize", "prune_oldest", "prune_least_recent", "hybrid"

## Outputs
- `compacted`: boolean — Whether compaction succeeded
- `tokens_before`: number — Token count before compaction
- `tokens_after`: number — Token count after compaction
- `pruned_count`: number — Number of entries pruned or summarized
- `metadata`: object — Strategy used, preserve list, timestamp

## Steps
1. Load current memory/context from agent state
2. Count tokens (or approximate by character count)
3. If under limit and no explicit request, return no-op
4. Apply strategy: summarize long blocks, prune oldest, or hybrid
5. For "summarize": use LLM or rule-based summary of older turns
6. For "prune": remove entries not in preserve list
7. Rebuild compacted context; verify token count
8. Persist compacted state; clear pruned entries
9. Return compacted status, token counts, pruned_count

## Example
```
Input: memory_type="conversation", strategy="prune_oldest", max_tokens=4000
Output: {
  compacted: true,
  tokens_before: 6500,
  tokens_after: 3800,
  pruned_count: 12,
  metadata: {strategy: "prune_oldest", preserved: ["positions"], timestamp: "2025-03-03T15:00:00Z"}
}
```
