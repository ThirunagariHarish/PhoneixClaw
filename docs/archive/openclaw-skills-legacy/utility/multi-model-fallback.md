# Multi-Model Fallback

## Purpose
Auto-switch LLM providers (OpenAI -> Anthropic -> local) on failure to maintain availability.

## Category
utility

## Triggers
- When primary LLM API returns error (rate limit, timeout, 5xx)
- When response fails validation or is malformed
- When user configures fallback chain
- On cold start to verify provider availability

## Inputs
- `prompt`: string — User or system prompt to send
- `fallback_chain`: string[] — Ordered list: ["openai", "anthropic", "local"]
- `model_map`: object — Provider -> model name (e.g., {openai: "gpt-4o", anthropic: "claude-3-sonnet"})
- `max_retries_per_provider`: number — Retries before next provider (default: 2)
- `timeout_ms`: number — Per-request timeout (default: 30000)

## Outputs
- `response`: string — Successful completion from first working provider
- `provider_used`: string — Which provider succeeded
- `model_used`: string — Model that returned response
- `attempts`: object[] — [{provider, error}] for failed attempts
- `latency_ms`: number — Total time including retries

## Steps
1. Iterate fallback_chain in order
2. For each provider: build request, call API with timeout and retries
3. On success: return response, provider_used, model_used, attempts, latency_ms
4. On failure: log error to attempts; continue to next provider
5. If all fail: raise error with full attempts log
6. Optionally report to llm-cost-tracker with provider_used

## Example
```
Input: prompt="Analyze AAPL trend", fallback_chain=["openai","anthropic","local"],
       model_map={openai:"gpt-4o", anthropic:"claude-3-sonnet", local:"llama3"}
Output: {
  response: "AAPL shows bullish momentum with...",
  provider_used: "anthropic",
  model_used: "claude-3-sonnet",
  attempts: [{provider: "openai", error: "RateLimitError"}],
  latency_ms: 4200
}
```

## Notes
- Local model may have different output format; normalize before use
- Consider cost when ordering chain; OpenAI often cheaper than Anthropic
- Use with llm-cost-tracker to monitor spend across providers
