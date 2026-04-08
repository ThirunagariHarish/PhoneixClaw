# Phase 15.3 — Historical Ingest + Embedding Store: Implementation Notes

**Phase ID:** 15.3  
**Feature:** Prediction Markets — LLM RAG Inference Pipeline (F15-F)  
**Date:** 2025  
**Status:** ✅ Complete

---

## What Changed

### New Files Created

| File | Purpose |
|------|---------|
| `agents/polymarket/data/__init__.py` | Package exports: `HistoricalIngestPipeline`, `EmbeddingStore`, `IngestResult`, `SimilarMarket` |
| `agents/polymarket/data/historical_ingest.py` | `HistoricalIngestPipeline` — fetches from venue and upserts to `pm_historical_markets` |
| `agents/polymarket/data/embedding_store.py` | `EmbeddingStore` — generates embeddings and supports cosine-similarity search |
| `tests/unit/test_pm_ingest.py` | 17 unit tests covering both classes |

### Existing Files Modified

None — Phase 15.1–15.2 files untouched as required.

---

## Implementation Details

### `HistoricalIngestPipeline`

- Accepts `AsyncSession` + `venue_name` (default: `"robinhood_predictions"`)
- Calls `get_venue(venue_name).fetch_markets(limit=max_markets)` to retrieve markets
- Maps venue dict fields to `PMHistoricalMarket` ORM columns:
  - `market_id` → `venue_market_id`
  - `title` → `question` (the actual DB column name)
  - `category` → `reference_class`
  - `yes_price` / `no_price` → stored in `price_history_json` (no dedicated column in schema)
  - `volume` → `volume_usd`
  - `end_date` → `resolution_date` (parsed via `datetime.fromisoformat().date()`)
  - `venue` → `venue`
  - `outcomes_json` → hardcoded `["Yes", "No"]` for binary markets
- Deduplication via `_market_already_exists(venue_market_id)` — single `SELECT … LIMIT 1` per market
- Returns `IngestResult(total_fetched, new_stored, skipped_duplicates)` frozen dataclass

### `EmbeddingStore`

- Accepts `AsyncSession` + optional `llm_client` (reserved for Phase 15.4+)
- `embed_unprocessed(batch_size)`: uses `LEFT OUTER JOIN` to find markets without embeddings, generates vectors, stores in `pm_market_embeddings`
- `find_similar(query_text, top_k)`: embeds query, loads all stored embeddings, computes Python-side cosine similarity, returns top-k sorted descending
- `_embed_text(text)`: checks `OPENAI_API_KEY` env var; if present, calls `openai.AsyncOpenAI.embeddings.create`; otherwise falls back to `_hash_embed`
- `_hash_embed(text)`: deterministic 1536-dim pseudo-embedding — SHA-256 digest tiled to 1536 byte values, then L2-normalised; works with **zero API keys**
- `_cosine_similarity(a, b)`: pure Python, handles zero-vectors gracefully (returns 0.0)

### Deviations from Spec

| Spec says | Actual | Reason |
|-----------|--------|--------|
| Map `title` → `question_text` | Maps to `question` | The DB column is named `question` (see models line 347); `question_text` does not exist |
| Map `end_date` → `resolved_at` | Maps to `resolution_date` (Date) | The DB column is `resolution_date: Date`; `resolved_at` does not exist |
| Store `yes_price` → `final_yes_price` | Stored in `price_history_json[0]` | No `final_yes_price` column in `PMHistoricalMarket`; price snapshot preserved in the existing JSONB list column |
| Files in `shared/polymarket/` (arch doc) | Files in `agents/polymarket/data/` | Task prompt explicitly specifies `agents/polymarket/data/`; task instructions take precedence over arch doc when they conflict |

---

## Tests Added

File: `tests/unit/test_pm_ingest.py` — **17 tests, all passing**

| Test | What it verifies |
|------|-----------------|
| `test_ingest_pipeline_stores_new_markets` | New markets get `session.add()` called; `IngestResult.new_stored == count` |
| `test_ingest_pipeline_deduplicates` | Second run with same market → `new_stored == 0`, `skipped_duplicates == 1` |
| `test_ingest_returns_correct_counts` | Mix of new/duplicate markets → all three `IngestResult` fields correct |
| `test_ingest_maps_fields_correctly` | Verifies `venue_market_id`, `question`, `reference_class`, `volume_usd`, `outcomes_json` |
| `test_embedding_store_embeds_unprocessed` | 3 unprocessed markets → 3 `PMMarketEmbedding` rows created with correct `embedding` length |
| `test_embedding_store_uses_hash_model_when_no_key` | No `OPENAI_API_KEY` → `model_used == _HASH_MODEL_ID` |
| `test_find_similar_returns_top_k` | 5 stored markets, query matches one exactly → top-1 similarity = 1.0; results sorted desc |
| `test_find_similar_returns_empty_when_no_embeddings` | Empty store → empty list |
| `test_cosine_similarity_identical_vectors` | Same vector → 1.0 |
| `test_cosine_similarity_orthogonal_vectors` | Orthogonal → 0.0 |
| `test_cosine_similarity_opposite_vectors` | Opposite → -1.0 |
| `test_cosine_similarity_zero_vector_returns_zero` | Zero vector → 0.0 (no ZeroDivisionError) |
| `test_hash_embedding_is_deterministic` | Same text → same vector (two calls) |
| `test_hash_embedding_different_texts_differ` | Different texts → different vectors |
| `test_hash_embedding_is_normalized` | L2 norm ≈ 1.0 |
| `test_hash_embedding_has_correct_dimension` | `len(v) == 1536` |
| `test_hash_embedding_empty_string` | Empty string → valid normalised 1536-dim vector |

### Test Strategy

- All DB-dependent tests use mock `AsyncSession` objects (not SQLite) to avoid
  PostgreSQL-specific type incompatibilities (`JSONB`, `UUID(as_uuid=True)`).
- `_market_already_exists` is patched directly on the pipeline instance so ingest
  tests focus on the storage logic, not the dedup SQL.
- `_hash_embed` fallback works with zero API keys — critical for CI.

---

## Build / Lint Results

```
ruff check agents/polymarket/data/ tests/unit/test_pm_ingest.py
All checks passed!

pytest tests/unit/ — 591 passed, 14 warnings (all pre-existing warnings unrelated to Phase 15.3)
```

Pre-existing `make test` `ImportPathMismatchError` (conftest collision between `tests/` and `apps/api/tests/`) is unrelated to Phase 15.3 — confirmed by running both suites independently.

---

## Open Risks / Notes for Phase 15.4

1. **No `final_yes_price` / `final_no_price` columns** — prices are stored in `price_history_json`. If Phase 15.4's scorer needs these as scalar floats, either add columns via migration or read from `price_history_json[0]["yes"]`.
2. **EmbeddingStore uses Python-side cosine similarity** — acceptable for Phase 15.3 per arch spec ("JSONB + Python cosine similarity for v1.0"), but will need pgvector for scale.
3. **`llm_client` parameter reserved** — `EmbeddingStore` accepts it but does not use it; Phase 15.4 LLM scorer will integrate here.
4. **No re-embed on model change** — existing `pm_market_embeddings` rows are not invalidated when a different embedding model is used. Recommend adding a `where model_used != current_model` filter if model upgrades are planned.
