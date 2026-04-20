"""
Async client for Ollama LLM service with retry logic and graceful fallback.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "mistral")
DEFAULT_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120"))
MAX_RETRIES = int(os.getenv("OLLAMA_MAX_RETRIES", "3"))
RETRY_BACKOFF = float(os.getenv("OLLAMA_RETRY_BACKOFF", "1.0"))


@dataclass
class GenerateResponse:
    text: str
    model: str
    total_duration_ms: float = 0.0
    prompt_eval_count: int = 0
    eval_count: int = 0
    done: bool = True


@dataclass
class OllamaClient:
    base_url: str = OLLAMA_BASE_URL
    default_model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = MAX_RETRIES
    retry_backoff: float = RETRY_BACKOFF
    fallback_models: list[str] = field(default_factory=lambda: ["mistral", "llama3.1"])
    _client: httpx.AsyncClient | None = field(default=None, repr=False, init=False)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def is_healthy(self) -> bool:
        try:
            client = await self._get_client()
            resp = await client.get("/api/tags", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def list_models(self) -> list[dict]:
        try:
            client = await self._get_client()
            resp = await client.get("/api/tags", timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
            return data.get("models", [])
        except Exception as e:
            logger.error("Failed to list Ollama models: %s", e)
            return []

    async def pull_model(self, model: str) -> bool:
        try:
            client = await self._get_client()
            resp = await client.post(
                "/api/pull",
                json={"name": model, "stream": False},
                timeout=httpx.Timeout(600.0, connect=10.0),
            )
            resp.raise_for_status()
            logger.info("Pulled model %s successfully", model)
            return True
        except Exception as e:
            logger.error("Failed to pull model %s: %s", model, e)
            return False

    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> GenerateResponse:
        """Generate a completion. Tries the primary model, then fallbacks."""
        models_to_try = [model or self.default_model]
        for fb in self.fallback_models:
            if fb not in models_to_try:
                models_to_try.append(fb)

        last_error: Exception | None = None
        for m in models_to_try:
            try:
                return await self._generate_with_retry(
                    prompt=prompt,
                    model=m,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
            except Exception as e:
                logger.warning("Model %s failed: %s, trying next", m, e)
                last_error = e

        logger.error("All models failed. Last error: %s", last_error)
        return GenerateResponse(
            text="",
            model=models_to_try[0],
            done=False,
        )

    async def _generate_with_retry(
        self,
        prompt: str,
        model: str,
        system: str | None,
        temperature: float,
        max_tokens: int | None,
        json_mode: bool,
    ) -> GenerateResponse:
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if system:
            payload["system"] = system
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        if json_mode:
            payload["format"] = "json"

        for attempt in range(1, self.max_retries + 1):
            try:
                client = await self._get_client()
                resp = await client.post("/api/generate", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return GenerateResponse(
                    text=data.get("response", ""),
                    model=model,
                    total_duration_ms=data.get("total_duration", 0) / 1e6,
                    prompt_eval_count=data.get("prompt_eval_count", 0),
                    eval_count=data.get("eval_count", 0),
                    done=data.get("done", True),
                )
            except httpx.TimeoutException:
                logger.warning("Timeout on attempt %d/%d for model %s", attempt, self.max_retries, model)
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(self.retry_backoff * attempt)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise  # model not found, fail fast
                logger.warning("HTTP %d on attempt %d/%d", e.response.status_code, attempt, self.max_retries)
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(self.retry_backoff * attempt)

        raise RuntimeError(f"Failed after {self.max_retries} retries")

    async def chat(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> GenerateResponse:
        """Chat completion with message history."""
        m = model or self.default_model
        payload: dict = {
            "model": m,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"

        for attempt in range(1, self.max_retries + 1):
            try:
                client = await self._get_client()
                resp = await client.post("/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                msg = data.get("message", {})
                return GenerateResponse(
                    text=msg.get("content", ""),
                    model=m,
                    total_duration_ms=data.get("total_duration", 0) / 1e6,
                    prompt_eval_count=data.get("prompt_eval_count", 0),
                    eval_count=data.get("eval_count", 0),
                    done=data.get("done", True),
                )
            except httpx.TimeoutException:
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(self.retry_backoff * attempt)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise
                if attempt == self.max_retries:
                    raise
                await asyncio.sleep(self.retry_backoff * attempt)

        raise RuntimeError(f"Chat failed after {self.max_retries} retries")


ollama_client = OllamaClient()
