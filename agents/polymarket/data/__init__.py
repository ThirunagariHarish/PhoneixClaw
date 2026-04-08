"""agents.polymarket.data — historical ingestion and embedding store (Phase 15.3)."""

from __future__ import annotations

from .embedding_store import EmbeddingStore, SimilarMarket
from .historical_ingest import HistoricalIngestPipeline, IngestResult

__all__ = [
    "EmbeddingStore",
    "HistoricalIngestPipeline",
    "IngestResult",
    "SimilarMarket",
]
