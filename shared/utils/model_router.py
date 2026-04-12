"""
Unified LLM Router — routes tasks to the cheapest capable model.

Three-Tier Architecture:
  Tier 1: Pure Python (no LLM)        — $0
  Tier 2: OpenRouter / Anthropic API   — cheap models via this router
  Tier 3: Claude SDK sessions          — reserved for live analyst + chat

This module handles ALL Tier 2 calls. Every call is:
  1. Routed to the right model by task_type
  2. Tracked for token usage (via token_tracker + budget_enforcer)
  3. Retried with fallback provider on failure

Providers:
  - openrouter: Primary (cheapest). Models prefixed with provider slug.
  - anthropic:  Fallback for Claude models. Direct Anthropic API.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
ANTHROPIC_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"

TASK_ROUTES: dict[str, str] = {
    # Tier 2 — cheap via OpenRouter
    "narrative": "anthropic/claude-3-haiku",
    "briefing_compile": "anthropic/claude-3-haiku",
    "trade_evaluation": "openai/gpt-4o-mini",
    "exit_decision": "openai/gpt-4o-mini",
    "risk_summary": "openai/gpt-4o-mini",
    "pattern_narrative": "openai/gpt-4o-mini",
    "headline_classify": "meta-llama/llama-3-8b-instruct",
    "data_format": "deepseek/deepseek-chat",
    "wiki_analysis": "openai/gpt-4o-mini",
    "supervisor_analysis": "openai/gpt-4o-mini",
    # Tier 2 — Sonnet-class for complex analysis
    "pattern_discovery": "anthropic/claude-sonnet-4-20250514",
    "strategy_analysis": "anthropic/claude-sonnet-4-20250514",
    "complex_reasoning": "anthropic/claude-sonnet-4-20250514",
    "auto_research": "anthropic/claude-sonnet-4-20250514",
    # Legacy aliases (backward compat with old callers)
    "summarization": "openai/gpt-4o-mini",
    "price_check": "deepseek/deepseek-chat",
    "lookup": "meta-llama/llama-3-8b-instruct",
    "research": "anthropic/claude-sonnet-4-20250514",
    "behavior_analysis": "anthropic/claude-sonnet-4-20250514",
    "strategy_generation": "anthropic/claude-sonnet-4-20250514",
}

MODEL_COSTS_PER_1M: dict[str, tuple[float, float]] = {
    "anthropic/claude-3-haiku": (0.25, 1.25),
    "anthropic/claude-sonnet-4-20250514": (3.0, 15.0),
    "openai/gpt-4o": (2.50, 10.0),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "deepseek/deepseek-chat": (0.14, 0.28),
    "meta-llama/llama-3-8b-instruct": (0.05, 0.15),
    "microsoft/phi-3-mini-4k-instruct": (0.20, 0.20),
    # Direct Anthropic model names (used when provider=anthropic)
    "claude-3-haiku": (0.25, 1.25),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-haiku": (0.80, 4.0),
    "claude-sonnet": (3.0, 15.0),
}


@dataclass
class LLMResponse:
    """Standardized response from any provider."""

    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    task_type: str = ""


@dataclass
class ModelRouter:
    """Unified LLM router with multi-provider support and usage tracking."""

    openrouter_api_key: str = ""
    anthropic_api_key: str = ""
    primary_provider: str = "openrouter"
    fallback_provider: str = "anthropic"
    default_model: str = "openai/gpt-4o-mini"
    agent_id: UUID | None = None
    _openrouter_client: httpx.AsyncClient | None = field(default=None, repr=False, init=False)
    _anthropic_client: httpx.AsyncClient | None = field(default=None, repr=False, init=False)

    def __post_init__(self) -> None:
        self.openrouter_api_key = self.openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.anthropic_api_key = self.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.primary_provider = os.getenv("LLM_PRIMARY_PROVIDER", self.primary_provider)
        self.fallback_provider = os.getenv("LLM_FALLBACK_PROVIDER", self.fallback_provider)

    async def _get_openrouter_client(self) -> httpx.AsyncClient:
        if self._openrouter_client is None or self._openrouter_client.is_closed:
            self._openrouter_client = httpx.AsyncClient(
                base_url=OPENROUTER_BASE,
                timeout=httpx.Timeout(90.0, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://cashflowus.com",
                    "X-Title": "Phoenix Trading Bot",
                },
            )
        return self._openrouter_client

    async def _get_anthropic_client(self) -> httpx.AsyncClient:
        if self._anthropic_client is None or self._anthropic_client.is_closed:
            self._anthropic_client = httpx.AsyncClient(
                base_url=ANTHROPIC_BASE,
                timeout=httpx.Timeout(120.0, connect=10.0),
                headers={
                    "x-api-key": self.anthropic_api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "Content-Type": "application/json",
                },
            )
        return self._anthropic_client

    async def close(self) -> None:
        for client in (self._openrouter_client, self._anthropic_client):
            if client and not client.is_closed:
                await client.aclose()
        self._openrouter_client = None
        self._anthropic_client = None

    def route(self, task_type: str, fallback: str | None = None) -> str:
        return TASK_ROUTES.get(task_type, fallback or self.default_model)

    async def complete(
        self,
        task_type: str,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        json_mode: bool = False,
        agent_id: UUID | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Route to optimal model and get completion with automatic tracking."""
        model = self.route(task_type, kwargs.pop("fallback", None))
        effective_agent_id = agent_id or self.agent_id

        providers = [self.primary_provider, self.fallback_provider]
        last_error: Exception | None = None

        for provider in providers:
            try:
                t0 = time.monotonic()
                if provider == "openrouter":
                    resp = await self._call_openrouter(
                        model, prompt, system, temperature, max_tokens, json_mode,
                    )
                elif provider == "anthropic":
                    resp = await self._call_anthropic(
                        model, prompt, system, temperature, max_tokens, json_mode,
                    )
                else:
                    raise ValueError(f"Unknown provider: {provider}")

                resp.latency_ms = (time.monotonic() - t0) * 1000
                resp.task_type = task_type
                resp.cost_usd = self._estimate_cost(resp.model, resp.input_tokens, resp.output_tokens)

                await self._track_usage(effective_agent_id, resp)
                return resp

            except Exception as e:
                last_error = e
                logger.warning(
                    "Provider %s failed for task=%s model=%s: %s. Trying fallback.",
                    provider, task_type, model, e,
                )

        logger.error("All providers failed for task=%s. Last error: %s", task_type, last_error)
        raise last_error or RuntimeError("All LLM providers failed")

    async def _call_openrouter(
        self,
        model: str,
        prompt: str,
        system: str | None,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        client = await self._get_openrouter_client()
        resp = await client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})

        return LLMResponse(
            text=choice.get("message", {}).get("content", ""),
            model=data.get("model", model),
            provider="openrouter",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    async def _call_anthropic(
        self,
        model: str,
        prompt: str,
        system: str | None,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
    ) -> LLMResponse:
        anthropic_model = self._to_anthropic_model(model)
        messages = [{"role": "user", "content": prompt}]

        payload: dict[str, Any] = {
            "model": anthropic_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if system:
            payload["system"] = system

        client = await self._get_anthropic_client()
        resp = await client.post("/v1/messages", json=payload)
        resp.raise_for_status()
        data = resp.json()

        text_parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        usage = data.get("usage", {})

        return LLMResponse(
            text="".join(text_parts),
            model=anthropic_model,
            provider="anthropic",
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    @staticmethod
    def _to_anthropic_model(model: str) -> str:
        """Convert OpenRouter model slug to direct Anthropic model name."""
        mapping = {
            "anthropic/claude-3-haiku": "claude-3-5-haiku-20241022",
            "anthropic/claude-sonnet-4-20250514": "claude-sonnet-4-20250514",
            "anthropic/claude-3-opus": "claude-3-opus-20240229",
        }
        if model in mapping:
            return mapping[model]
        if model.startswith("anthropic/"):
            return model.removeprefix("anthropic/")
        return model

    @staticmethod
    def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        costs = MODEL_COSTS_PER_1M.get(model)
        if not costs:
            for key, val in MODEL_COSTS_PER_1M.items():
                if model.startswith(key) or key in model:
                    costs = val
                    break
        if not costs:
            costs = (3.0, 15.0)  # default to Sonnet pricing
        return round(
            (input_tokens / 1_000_000) * costs[0] + (output_tokens / 1_000_000) * costs[1],
            6,
        )

    async def _track_usage(self, agent_id: UUID | None, resp: LLMResponse) -> None:
        """Record usage to both token_tracker and budget_enforcer (best-effort)."""
        if resp.input_tokens == 0 and resp.output_tokens == 0:
            return
        try:
            from apps.api.src.services.token_tracker import record_usage as tt_record

            await tt_record(
                instance_id=None,
                agent_id=agent_id,
                model=resp.model,
                input_tokens=resp.input_tokens,
                output_tokens=resp.output_tokens,
            )
        except Exception as e:
            logger.debug("token_tracker.record_usage failed (non-fatal): %s", e)

        if agent_id:
            try:
                from apps.api.src.services.budget_enforcer import record_usage as be_record

                result = await be_record(
                    agent_id=agent_id,
                    model=resp.model,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                )
                if result.get("auto_paused"):
                    logger.warning(
                        "Agent %s auto-paused by budget enforcer after %s call",
                        agent_id, resp.task_type,
                    )
            except Exception as e:
                logger.debug("budget_enforcer.record_usage failed (non-fatal): %s", e)

    def estimate_cost(self, task_type: str, input_tokens: int, output_tokens: int | None = None) -> float:
        model = self.route(task_type)
        return self._estimate_cost(model, input_tokens, output_tokens or input_tokens)


def get_router(agent_id: UUID | None = None) -> ModelRouter:
    """Factory: create a ModelRouter with env-configured keys."""
    return ModelRouter(agent_id=agent_id)
