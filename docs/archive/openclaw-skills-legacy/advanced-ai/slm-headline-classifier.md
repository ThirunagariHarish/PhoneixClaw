# SLM Headline Classifier

## Purpose
Use Small Language Models (Phi-3, Llama 3B/8B) for sub-second headline classification: sentiment, relevance, urgency.

## Category
advanced-ai

## Triggers
- When processing high-volume news feed and latency matters
- When screening headlines for trading signals in real time
- When GPT-4 latency/cost is prohibitive for simple classification
- When running on edge or resource-constrained environments

## Inputs
- `headlines`: string[] — Raw headline text (batch for efficiency)
- `model`: string — "phi-3-mini", "llama-3b", "llama-8b", "auto" (default: "auto")
- `labels`: string[] — Classification labels (e.g., ["bullish", "bearish", "neutral", "irrelevant"])
- `symbols`: string[] — Optional: symbols to score relevance for
- `max_latency_ms`: number — Target max latency (default: 500)
- `batch_size`: number — Headlines per batch (default: 8)

## Outputs
- `classifications`: object[] — [{headline, label, confidence, relevance_score}]
- `latency_ms`: number — Actual inference latency
- `model_used`: string — Model that handled the request
- `aggregate`: object — {bullish: n, bearish: n, neutral: n, irrelevant: n}
- `metadata`: object — batch_size, model, timestamp

## Steps
1. Select model: "auto" -> choose smallest model that fits max_latency_ms
2. Load model (local or via fast API); use quantization (int4/int8) if needed
3. Format prompts: "Classify: {headline} -> {labels}"
4. Batch inference; run in parallel if batch_size > 1
5. Parse outputs: extract label and confidence (logits or softmax)
6. If symbols: add relevance scoring (entity match or second pass)
7. Compute aggregate counts per label
8. Return classifications, latency_ms, model_used, aggregate, metadata
9. Cache model in memory for repeated calls
10. Fallback to rule-based (keyword) if model fails

## Example
```
Input: headlines=["Fed signals rate cut in Q2", "AAPL misses earnings"], labels=["bullish","bearish","neutral","irrelevant"]
Output: {
  classifications: [
    {headline: "Fed signals rate cut in Q2", label: "bullish", confidence: 0.82, relevance_score: 0.9},
    {headline: "AAPL misses earnings", label: "bearish", confidence: 0.91, relevance_score: 0.95}
  ],
  latency_ms: 180,
  model_used: "phi-3-mini",
  aggregate: {bullish: 1, bearish: 1, neutral: 0, irrelevant: 0},
  metadata: {batch_size: 2, timestamp: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Phi-3-mini, Llama-3B run in <200ms on GPU; CPU may be 1–2s
- Quantization (bitsandbytes, llama.cpp) reduces memory and speeds inference
- For very high throughput, consider dedicated inference server (vLLM, TGI)
