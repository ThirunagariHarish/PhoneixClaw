"""Centralized LLM model pricing.

Phase H7: Single source of truth. Previously, pricing was duplicated in
`token_tracker.py` and `token_usage.py` with conflicting values.

All prices are in USD per 1 million tokens (input / output split).
"""
from __future__ import annotations

# Per-1M-tokens pricing in USD
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Claude 4.x family
    "claude-opus-4": {"input": 15.0, "output": 75.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    "claude-opus-4-1-20250805": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-sonnet-4-5-20250929": {"input": 3.0, "output": 15.0},
    "claude-haiku-4": {"input": 0.80, "output": 4.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    # Claude 3.x family
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.0},
    "claude-3-opus-20240229": {"input": 15.0, "output": 75.0},
    # Aliases
    "claude-opus": {"input": 15.0, "output": 75.0},
    "claude-sonnet": {"input": 3.0, "output": 15.0},
    "claude-haiku": {"input": 0.80, "output": 4.0},
    # OpenAI (for fallback chains)
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}

DEFAULT_PRICING = {"input": 3.0, "output": 15.0}  # Sonnet baseline


def get_pricing(model: str) -> dict[str, float]:
    """Return {input, output} per-1M USD pricing for a model. Falls back to default."""
    if not model:
        return DEFAULT_PRICING
    # Try exact match first
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    # Try prefix match (e.g., "claude-sonnet-4-some-suffix")
    for key in MODEL_PRICING:
        if model.startswith(key):
            return MODEL_PRICING[key]
    return DEFAULT_PRICING


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute USD cost for an LLM call."""
    pricing = get_pricing(model)
    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    return round(input_cost + output_cost, 6)
