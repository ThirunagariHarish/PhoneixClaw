# Multi-Model Router

## Purpose
Route LLM tasks to optimal model: GPT-4o for complex reasoning, Llama/DeepSeek for simple lookups via OpenRouter to balance cost and quality.

## Category
utility

## Triggers
- When agent needs to call an LLM for any task
- When user requests cost-efficient or fast LLM responses
- When task complexity can be classified (simple vs complex)
- When switching between reasoning-heavy and lookup-heavy workloads

## Inputs
- `prompt`: string — User or system prompt
- `task_type`: string — "reasoning", "lookup", "classification", "generation", "auto"
- `max_tokens`: number — Max response tokens (default: 1024)
- `preferred_provider`: string — "openai", "openrouter", "local" (default: "openrouter")
- `complexity_hint`: string — Optional: "simple", "complex" to override auto-detect
- `fallback_on_error`: boolean — Use fallback model if primary fails (default: true)

## Outputs
- `model_used`: string — Model that handled the request (e.g., "gpt-4o", "meta-llama/llama-3-70b")
- `response`: string — LLM response text
- `usage`: object — {prompt_tokens, completion_tokens, total_tokens}
- `latency_ms`: number — Response latency
- `cost_estimate`: number — Estimated cost in USD
- `metadata`: object — task_type, routing_reason, fallback_used

## Steps
1. If task_type="auto": classify prompt (length, keywords, structure) -> "simple" or "complex"
2. For "reasoning", "generation", "complex": route to GPT-4o or Claude
3. For "lookup", "classification", "simple": route to Llama, DeepSeek, or smaller model via OpenRouter
4. Build API request for selected model (OpenRouter or direct)
5. Execute request; capture response, usage, latency
6. If error and fallback_on_error: retry with fallback model (e.g., GPT-4o)
7. Estimate cost from usage and model pricing
8. Return model_used, response, usage, latency_ms, cost_estimate, metadata
9. Log routing decisions for cost/quality analysis
10. Cache simple lookups when appropriate

## Example
```
Input: prompt="What is the market cap of AAPL?", task_type="lookup", preferred_provider="openrouter"
Output: {
  model_used: "meta-llama/llama-3-70b-instruct",
  response: "Apple Inc. (AAPL) has a market cap of approximately $2.8T...",
  usage: {prompt_tokens: 15, completion_tokens: 45, total_tokens: 60},
  latency_ms: 1200,
  cost_estimate: 0.00012,
  metadata: {task_type: "lookup", routing_reason: "simple lookup -> cost-efficient model"}
}
```

## Notes
- OpenRouter provides unified API for many models; configure API key
- Auto-classification can use prompt length, question marks, or a tiny classifier
- Cost estimates require model pricing table; update periodically
