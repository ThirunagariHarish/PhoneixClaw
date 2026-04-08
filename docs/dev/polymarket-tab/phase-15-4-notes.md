# Phase 15.4 Implementation Notes — Scorer Chain

**Phase:** 15.4  
**Feature:** Prediction Markets — Full Scorer Chain (Heuristic + LLM + CoT + Bull/Bear/Judge + Reference Class)  
**Date:** 2025-07-10  
**Author:** Devin (Implementation Engineer)

---

## What Changed

### New Files

| File | Purpose |
|------|---------|
| `agents/polymarket/top_bets/config.yaml` | Scorer YAML config (weights, thresholds, LLM model, cost cap) |
| `agents/polymarket/top_bets/reference_class.py` | `ReferenceClassScorer` — anchors probability on historical base-rate |
| `agents/polymarket/top_bets/cot_sampler.py` | `CoTSampler` — N=5 parallel LLM calls with trimmed mean |
| `agents/polymarket/top_bets/debate_scorer.py` | `DebateScorer` — Bull/Bear/Judge adversarial pipeline |
| `agents/polymarket/top_bets/llm_scorer.py` | `LLMScorer` — orchestrates full chain, weighted blend |
| `agents/polymarket/top_bets/scorer.py` | `TopBetScorer` — heuristic pre-filter + batch orchestration |
| `agents/polymarket/top_bets/model_evaluator.py` | `ModelEvaluator` — running Brier score & calibration tracking |
| `agents/polymarket/top_bets/__init__.py` | Package exports for all scorer classes |
| `tests/unit/test_pm_scorer.py` | 29 unit tests covering all scorer components |

### Modified Files (Python 3.9 Compatibility Fix)

Added `from __future__ import annotations` to all `shared/db/models/*.py` files that used Python 3.10+ union type syntax (`X | None`) in class-level type annotations. This is needed because SQLAlchemy evaluates `Mapped[]` annotations at mapper-configuration time via `eval()`, which does not support `X | None` syntax on Python 3.9. The import defers annotation evaluation to strings (PEP 563), making the models importable on both Python 3.9 and 3.11+.

**Note:** The SQLAlchemy `eval()` pathway still rejects `uuid.UUID | None` strings on Python 3.9. The tests use `sys.modules` stubs for the entire `shared.db` layer so no SQLAlchemy ORM initialisation occurs during unit testing. This is the standard approach for unit tests that don't need a real DB.

---

## Architecture Decisions & Deviations

### Weighted Blend Formula
The spec says `final = ref_class_weight*base_rate + llm_weight*cot_mean + (debate_weight*debate if available)`.  
**Implementation:** When debate is absent, the ref+llm weights are normalised to sum to 1.0 (not including the heuristic weight, which is applied by `TopBetScorer` at the outer layer). When debate is present, the remaining weight after ref_class is split 50/50 between cot_mean and debate. This keeps the output bounded in [0, 1] and follows the architecture intent.

### Reference Class Base Rate
The `SimilarMarket` objects returned by `EmbeddingStore.find_similar()` don't include `final_yes_price`. The implementation uses `PMHistoricalMarket.winning_outcome == "YES"` as a binary proxy (1.0/0.0). This requires a supplemental DB query via `embedding_store.db`. The `ReferenceClassScorer` constructor signature `__init__(self, embedding_store)` is preserved as specified; the DB session is accessed via `embedding_store.db` attribute.

### Model Evaluator Storage Pattern
`PMModelEvaluation` is an aggregate row (not per-prediction). `record_prediction` uses an incremental running-mean formula:
```
new_mean = (old_mean * n + new_value) / (n + 1)
```
This keeps the table O(1) in size per model type and avoids storing individual prediction history.

### SQLAlchemy `select()` Mocking in Tests
The production code uses `select(ModelClass).where(ModelClass.field == value)` which requires SQLAlchemy mapped classes. In unit tests, these are stubbed with plain Python classes. Tests patch `agents.polymarket.top_bets.*.select` to return a `MagicMock()` so the SQLAlchemy coercion path never runs. The `db.execute()` mock returns pre-configured results directly.

---

## Files Touched

**New production files:**
- `agents/polymarket/top_bets/__init__.py`
- `agents/polymarket/top_bets/config.yaml`
- `agents/polymarket/top_bets/cot_sampler.py`
- `agents/polymarket/top_bets/debate_scorer.py`
- `agents/polymarket/top_bets/llm_scorer.py`
- `agents/polymarket/top_bets/model_evaluator.py`
- `agents/polymarket/top_bets/reference_class.py`
- `agents/polymarket/top_bets/scorer.py`

**New test files:**
- `tests/unit/test_pm_scorer.py`

**Modified for Python 3.9 compat (adding `from __future__ import annotations`):**
- `shared/db/models/agent.py`
- `shared/db/models/agent_chat.py`
- `shared/db/models/agent_message.py`
- `shared/db/models/agent_metric.py`
- `shared/db/models/agent_session.py`
- `shared/db/models/agent_trade.py`
- `shared/db/models/api_key.py`
- `shared/db/models/audit_log.py`
- `shared/db/models/backtest_trade.py`
- `shared/db/models/connector.py`
- `shared/db/models/dev_incident.py`
- `shared/db/models/error_log.py`
- `shared/db/models/learning_session.py`
- `shared/db/models/notification.py`
- `shared/db/models/polymarket.py`
- `shared/db/models/skill.py`
- `shared/db/models/strategy.py`
- `shared/db/models/system_log.py`
- `shared/db/models/task.py`
- `shared/db/models/token_usage.py`
- `shared/db/models/trade.py`
- `shared/db/models/trade_signal.py`
- `shared/db/models/trading_account.py`
- `shared/db/models/user.py`
- `shared/db/models/watchlist.py`

---

## Tests Added (`tests/unit/test_pm_scorer.py`)

| Test | What It Verifies |
|------|-----------------|
| `test_reference_class_uniform_prior_when_few_similar` | <3 resolved comps → base_rate=0.5, confidence=0.1 |
| `test_reference_class_computes_base_rate_correctly` | 4 YES / 5 resolved → base_rate=0.8 |
| `test_reference_class_no_similar_markets` | Empty find_similar → uniform prior |
| `test_reference_class_ignores_unresolved_markets` | None winning_outcome excluded from base_rate |
| `test_cot_sampler_trims_outliers` | Min+max dropped for n≥5 before mean |
| `test_cot_sampler_parallel_calls` | All N calls fired concurrently (asyncio.gather) |
| `test_cot_graceful_degradation` | All LLM calls fail → mean=0.5, std_dev=0.5, empty samples |
| `test_cot_sampler_partial_failure_above_threshold` | 3/5 succeed → valid result (no degradation) |
| `test_cot_sampler_uses_config_model` | Config `llm.model` and temperature forwarded to generate() |
| `test_debate_scorer_three_sequential_calls` | Exactly 3 calls: Bull → Bear → Judge in order |
| `test_debate_scorer_confidence_adjustment` | adjustment = final_yes_prob - cot_estimate |
| `test_debate_scorer_fallback_on_unparseable_judge` | Unparseable judge response → fallback to cot_estimate |
| `test_llm_scorer_blends_weights_correctly` | Fixed inputs verify weighted blend math |
| `test_llm_scorer_with_debate_blends_three_way` | Debate present → ref + half_cot + half_debate |
| `test_llm_scorer_score_market_no_debate` | End-to-end no-debate path completes |
| `test_llm_scorer_confidence_equals_one_minus_std` | Identical CoT samples → confidence ≈ 1.0 |
| `test_top_bet_scorer_runs_debate_only_top5` | 20 markets in → debate called exactly 5 times |
| `test_heuristic_score_prefers_liquid_near_50pct` | High volume + central price → high heuristic score |
| `test_heuristic_time_horizon_penalty` | Outside 7–60 day window → lower score |
| `test_heuristic_score_components_range` | All sub-scores in [0, 1] for boundary values |
| `test_model_evaluator_brier_score_known_values` | Known predictions verify Brier formula |
| `test_model_evaluator_accuracy_tracking` | Correct/incorrect predictions update accuracy |
| `test_model_evaluator_compute_brier_score_no_data` | No data → returns 0.25 (uniform prior) |
| `test_model_evaluator_get_calibration_metrics` | Returns correct dict shape |
| `test_cot_parse_last_float` | Last float extracted and clamped to [0,1] |
| `test_trimmed_mean_drops_min_max` | Min and max dropped for n≥5 |
| `test_trimmed_mean_with_fewer_than_5` | Plain mean for n<5 |
| `test_std_dev_identical_samples` | Identical samples → std_dev = 0 |
| `test_std_dev_single_sample` | Single sample → std_dev = 0 |

All 29 tests pass.

---

## Open Risks

1. **Python 3.9 / SQLAlchemy ORM init on Python 3.9**: The `from __future__ import annotations` fix defers annotation evaluation to strings, but SQLAlchemy's eval-based annotation resolution in `mapped_column()` still fails on Python 3.9 for `X | None` syntax. The proper fix is to change all `Mapped[X | None]` to `Mapped[Optional[X]]` across the model files, but that is a larger refactor outside Phase 15.4 scope. The test suite works around this with `sys.modules` stubs.

2. **Reference class base-rate accuracy**: The base-rate computation uses `winning_outcome == "YES"` (binary) rather than the final market price. For markets that resolved near 0 or 1 but not exactly, this is a simplification. A future enhancement could use `outcomes_json` to get the final price.

3. **Cost cap enforcement**: `max_daily_debate_calls: 100` is defined in config but not enforced at the scorer level (it would require a persistent counter in Redis/DB). This is a known gap — enforcement should be added in Phase 15.5 or a dedicated rate-limiter.

4. **LLM client interface**: The scorer chain calls `llm_client.generate(prompt, model=..., temperature=..., max_tokens=...)`. The existing `OllamaClient` supports all these kwargs. If the Anthropic/Claude client is used, the interface may differ — the injected `llm_client` must be a wrapper that maps to the Claude API's `generate` interface.
