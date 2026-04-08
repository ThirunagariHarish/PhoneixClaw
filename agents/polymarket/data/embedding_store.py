"""Embedding store for prediction-market similarity search (Phase 15.3).

Generates vector embeddings for historical markets and supports top-k
cosine-similarity retrieval.  Uses the OpenAI ``text-embedding-3-small``
model when ``OPENAI_API_KEY`` is available; falls back to a deterministic
hash-based pseudo-embedding so that CI and local development work without
any paid API access.

Reference: docs/architecture/polymarket-phase15.md § 7 (Embedding Store),
           docs/prd/polymarket-phase15.md F15-F2.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.polymarket import PMHistoricalMarket, PMMarketEmbedding

logger = logging.getLogger(__name__)

# Model identifier stored alongside each embedding so future re-embeds can
# detect stale rows when the model changes.
_HASH_MODEL_ID = "hash-sha256-v1"
_OPENAI_MODEL_ID = "text-embedding-3-small"

# Dimensionality matches OpenAI text-embedding-3-small (and many others).
_EMBED_DIM = 1536


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimilarMarket:
    """One item returned by :meth:`EmbeddingStore.find_similar`."""

    market_id: uuid.UUID
    question_text: str
    similarity_score: float
    reference_class: Optional[str]


# ---------------------------------------------------------------------------
# EmbeddingStore
# ---------------------------------------------------------------------------


class EmbeddingStore:
    """Generate, persist, and query market embeddings.

    Args:
        db_session: An active :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        llm_client:  Reserved for future LLM client injection; currently
            unused — embeddings are obtained via OpenAI API or the hash
            fallback.
    """

    def __init__(self, db_session: AsyncSession, llm_client: Any = None) -> None:
        self.db = db_session
        self.llm_client = llm_client  # reserved for Phase 15.4+

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def embed_unprocessed(self, batch_size: int = 50) -> int:
        """Embed all :class:`PMHistoricalMarket` rows that lack an embedding.

        Args:
            batch_size: Maximum number of markets to process in one call.

        Returns:
            Number of new :class:`PMMarketEmbedding` rows created.
        """
        stmt = (
            select(PMHistoricalMarket)
            .outerjoin(PMMarketEmbedding, PMMarketEmbedding.historical_market_id == PMHistoricalMarket.id)
            .where(PMMarketEmbedding.id.is_(None))
            .limit(batch_size)
        )
        result = await self.db.execute(stmt)
        markets: list[PMHistoricalMarket] = list(result.scalars().all())

        count = 0
        for market in markets:
            text = self._build_embed_text(market)
            vector = await self._embed_text(text)
            model_used = _OPENAI_MODEL_ID if self._has_openai_key() else _HASH_MODEL_ID

            embedding_row = PMMarketEmbedding(
                historical_market_id=market.id,
                embedding=vector,
                model_used=model_used,
            )
            self.db.add(embedding_row)
            count += 1

        await self.db.flush()
        logger.info("embed_unprocessed created %d new embedding rows", count)
        return count

    async def find_similar(self, query_text: str, top_k: int = 10) -> list[SimilarMarket]:
        """Find the *top_k* most similar historical markets to *query_text*.

        Loads all stored embeddings, computes cosine similarity in Python,
        and returns a ranked list.

        Args:
            query_text: Free-form text to search against.
            top_k:      Maximum number of results to return.

        Returns:
            List of :class:`SimilarMarket` sorted by similarity descending.
        """
        query_vector = await self._embed_text(query_text)

        # Load all embeddings joined with their parent market
        stmt = select(PMMarketEmbedding, PMHistoricalMarket).join(
            PMHistoricalMarket, PMMarketEmbedding.historical_market_id == PMHistoricalMarket.id
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        scored: list[tuple[float, PMMarketEmbedding, PMHistoricalMarket]] = []
        for emb, market in rows:
            if not emb.embedding:
                continue
            sim = self._cosine_similarity(query_vector, emb.embedding)
            scored.append((sim, emb, market))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            SimilarMarket(
                market_id=market.id,
                question_text=market.question,
                similarity_score=sim,
                reference_class=market.reference_class,
            )
            for sim, _emb, market in scored[:top_k]
        ]

    # ------------------------------------------------------------------
    # Embedding helpers
    # ------------------------------------------------------------------

    async def _embed_text(self, text: str) -> list[float]:
        """Return a 1536-dimensional float vector for *text*.

        Uses OpenAI ``text-embedding-3-small`` when ``OPENAI_API_KEY`` is
        set.  Falls back to a deterministic hash-based pseudo-embedding
        otherwise so that CI and offline development work without any
        API key.
        """
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                import openai  # noqa: PLC0415  (deferred import — optional dep)

                client = openai.AsyncOpenAI(api_key=openai_key)
                resp = await client.embeddings.create(input=text, model=_OPENAI_MODEL_ID)
                return list(resp.data[0].embedding)
            except Exception as exc:  # noqa: BLE001
                logger.warning("openai embedding failed, using hash fallback: %s", exc)

        return self._hash_embed(text)

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Return the cosine similarity between vectors *a* and *b*.

        Both vectors must have the same length.  Returns 0.0 for zero
        vectors to avoid division-by-zero errors.
        """
        if len(a) != len(b):
            raise ValueError(f"Vector length mismatch: {len(a)} vs {len(b)}")

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))

        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ------------------------------------------------------------------
    # Private utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_embed(text: str) -> list[float]:
        """Deterministic, normalised 1536-dim pseudo-embedding for *text*.

        Derived from the SHA-256 digest of the UTF-8 encoded text, tiled
        to 1536 byte-values, then L2-normalised.  Identical inputs always
        produce identical outputs; this makes tests fast and free of any
        external service dependency.
        """
        digest = hashlib.sha256(text.encode()).digest()  # 32 bytes
        # Tile digest bytes until we have exactly 1536 values
        tiled = (digest * 48)[:_EMBED_DIM]  # 32 * 48 = 1536
        raw = [float(b) for b in tiled]
        norm = math.sqrt(sum(v * v for v in raw))
        if norm == 0.0:
            return raw
        return [v / norm for v in raw]

    @staticmethod
    def _build_embed_text(market: PMHistoricalMarket) -> str:
        """Build the text string to embed for *market*.

        Follows the PRD F15-F2 template::

            {question}
            Category: {category}
            Outcome: {winning_outcome}
        """
        parts = [market.question or ""]
        if market.reference_class:
            parts.append(f"Category: {market.reference_class}")
        if market.winning_outcome:
            parts.append(f"Outcome: {market.winning_outcome}")
        return "\n".join(parts)

    @staticmethod
    def _has_openai_key() -> bool:
        """Return ``True`` if an OpenAI API key is present in the environment."""
        return bool(os.getenv("OPENAI_API_KEY"))
