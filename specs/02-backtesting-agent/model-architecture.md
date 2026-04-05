# Spec: Multi-Modal Model Architecture

## Purpose

Dedicated architecture spec for the 8-model training pipeline. Defines data modalities, model architectures, preprocessing pipeline, resource requirements, inference latency targets, and model versioning.

---

## 4 Data Modalities

| Modality | Shape | Source | Preprocessing |
|----------|-------|--------|----------------|
| Tabular | (1, ~200) | Enriched features from `enrich.py` | Impute NaN (median), `StandardScaler`, persist imputer + scaler as `.pkl` |
| Candle Windows | (30, 15) | yfinance 5m bars anchored around trade time | 30 bars × `[open, high, low, close, volume, rsi_14, macd_line, macd_signal, bb_upper, bb_lower, atr_14, obv, vwap, ema_9, sma_20]`; per-feature min–max normalize to [0, 1]; persist candle scaler as `.pkl` |
| Text Embeddings | (1, 384) | `sentence-transformers` `all-MiniLM-L6-v2` on raw Discord message | Batch encode; save as `.npy` aligned to row keys / trade IDs |
| Categoricals | (1, ~10) | `analyst_id`, `ticker`, `day_of_week`, `hour_bucket`, `option_type`, `market_regime`, `signal_type`, `vix_regime` (and related low-cardinality fields as schema evolves) | Integer-encode for neural nets; native categorical columns for CatBoost |

**Notes**

- Tabular and categoricals must share the same row index as labels and as candle/text tensors after joins.
- Candle windows are fixed length (30); missing history should be handled explicitly (pad, mask, or drop) in preprocessing—document the chosen policy in `preprocess.py`.
- Text is optional per row; define a zero or learned “missing text” embedding policy for multimodal models.

---

## 8 Model Types

For each model: **name**, **type** (tabular / sequence / multimodal), **input modalities**, **architecture summary**, **key hyperparameters**, **expected training time**, **inference latency** (single forward pass on CPU unless noted).

### 1. XGBoost

| Field | Value |
|-------|--------|
| **Type** | Tabular |
| **Modalities** | Tabular only (~200 features) |
| **Architecture** | Gradient-boosted trees on flat feature vector |
| **Key hyperparameters** | ~500 trees, max depth 6, learning rate 0.05 (tune via validation) |
| **Training time** | ~2 min (representative; scales with data size) |
| **Inference latency** | ~1 ms |

### 2. LightGBM

| Field | Value |
|-------|--------|
| **Type** | Tabular |
| **Modalities** | Tabular only |
| **Architecture** | Leaf-wise gradient boosting |
| **Key hyperparameters** | ~500 trees, max depth 8, `num_leaves` 63 |
| **Training time** | ~1.5 min |
| **Inference latency** | &lt;1 ms |

### 3. Random Forest

| Field | Value |
|-------|--------|
| **Type** | Tabular |
| **Modalities** | Tabular only |
| **Architecture** | Bagged decision trees |
| **Key hyperparameters** | 500 estimators, max depth 12 |
| **Training time** | ~3 min |
| **Inference latency** | ~2 ms |

### 4. CatBoost

| Field | Value |
|-------|--------|
| **Type** | Tabular (+ categoricals) |
| **Modalities** | Tabular + categoricals (native cat features) |
| **Architecture** | Ordered boosting with categorical handling |
| **Key hyperparameters** | 1000 iterations, depth 8, native categorical indices / column spec |
| **Training time** | ~5 min |
| **Inference latency** | ~1 ms |

### 5. LSTM (Fixed)

| Field | Value |
|-------|--------|
| **Type** | Multimodal (sequence + tabular) |
| **Modalities** | Candle windows (30×15) + tabular (~200 → projected) |
| **Architecture** | `LSTM(input_dim=15, hidden=128, num_layers=2)` on candle sequence; parallel `Linear(200→64)` (or equivalent) on tabular; concatenate (or add with broadcast where justified) → MLP classifier |
| **Key hyperparameters** | Hidden 128, 2 LSTM layers, dropout on LSTM/MLP heads, Adam + weight decay |
| **Training time** | ~15 min (CPU); faster with GPU |
| **Inference latency** | ~5 ms on CPU |

### 6. Transformer (Fixed)

| Field | Value |
|-------|--------|
| **Type** | Multimodal (sequence + tabular) |
| **Modalities** | Candle windows + tabular |
| **Architecture** | Per-timestep `Linear(15→128)` + sinusoidal or learned positional encoding → `TransformerEncoder` (4 heads, 2 layers) → pooled sequence representation; tabular `Linear(200→64)` → fusion → classifier |
| **Key hyperparameters** | d_model 128, 4 heads, 2 encoder layers, FFN dim ~512, dropout |
| **Training time** | ~20 min (CPU); faster with GPU |
| **Inference latency** | ~8 ms on CPU |

### 7. Temporal Fusion Transformer (TFT)

| Field | Value |
|-------|--------|
| **Type** | Multimodal (full stack) |
| **Modalities** | All: static/tabular reals, static categoricals, time-varying candle features per step, and text embedding as static or time-constant covariate (explicitly map in implementation) |
| **Architecture** | `pytorch_forecasting` TFT: variable selection networks, LSTM encoder–decoder context, interpretable multi-horizon outputs; for classification, attach a head on the relevant decoder output or repurpose forecast logits per spec in `train_tft.py` |
| **Key hyperparameters** | Hidden size, attention heads, dropout, learning rate, max epochs; early stopping on validation metric |
| **Training time** | ~30 min (CPU baseline); GPU recommended |
| **Inference latency** | ~15 ms on CPU |

### 8. Hybrid Ensemble

| Field | Value |
|-------|--------|
| **Type** | Multimodal |
| **Modalities** | All: LSTM (or GRU) candle encoder + text projection (384→d) + tabular projection (200→d) → fusion layer (concat / gated fusion) → classifier |
| **Architecture** | Three-branch encoder with shared embedding dimension; fusion MLP; optional auxiliary losses |
| **Key hyperparameters** | Branch hidden dims, fusion depth, dropout, label smoothing if used |
| **Training time** | ~25 min (CPU); GPU recommended |
| **Inference latency** | ~10 ms on CPU |

**Stack-level ensemble**

- Tree models (XGBoost, LightGBM, RF, CatBoost) and neural checkpoints feed a **meta-learner** (`train_meta_learner.py`) for stacked or blended predictions; hyperparameters and validation strategy for the meta-learner belong in that script’s docstring and `meta.json`.

---

## Preprocessing Pipeline

Flow from raw enriched parquet to four modality artifacts consumed by trainers.

```
enriched.parquet
    │
    ├── preprocess.py
    │     ├── Extract tabular features → X_tabular.npy
    │     ├── Extract categoricals → X_categoricals.npy
    │     └── Time-based train/val/test split
    │
    ├── compute_text_embeddings.py
    │     └── Encode Discord messages → X_text.npy
    │
    └── (enrich.py already produced candle_windows.npy)
```

**Contract**

1. **Input**: `enriched.parquet` with stable column names, row IDs, timestamps, labels, and references to raw message text (or pre-joined text).
2. **`preprocess.py`**: Emits `X_tabular.npy`, `X_categoricals.npy`, split indices (or separate split files), `imputer.pkl`, `scaler.pkl`, and documents alignment keys for merging with `candle_windows.npy` and `X_text.npy`.
3. **`compute_text_embeddings.py`**: Loads text by row key; batch encodes with `all-MiniLM-L6-v2`; writes `X_text.npy` with same ordering as tabular splits (or a join manifest).
4. **Candle windows**: Assumed produced upstream by `enrich.py` as `candle_windows.npy` (or path configured in meta); same alignment as above.

---

## Resource Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 4 cores | 8 cores |
| RAM | 8 GB | 16 GB |
| Disk | 10 GB | 20 GB |
| GPU | Not required | CUDA optional for LSTM / Transformer / TFT / Hybrid |

All models can train on CPU. GPU typically speeds neural models by approximately 3–5×; tree libraries remain CPU-bound unless using GPU-specific builds explicitly added to the stack.

---

## Inference Latency Budget

**Total budget**: 3 seconds from signal detection to order placement.

| Step | Budget | Method |
|------|--------|--------|
| Parse signal | 10 ms | Python regex (or existing parser) |
| Enrich (cached) | 500 ms | yfinance with ~60 s cache |
| ML inference | 100 ms | `model.predict()` (and meta-learner if used) on CPU |
| Risk check | 10 ms | Python rules |
| Order placement | 1000 ms | Robinhood API |
| Buffer | 1380 ms | Safety margin |

Neural models in this spec are sized so a **single** forward pass stays within the ML row budget; full 8-model + meta stack must either run in parallel within the 100 ms slice or use a reduced deployment subset with documented tradeoffs.

---

## Model Versioning

Each training run produces a **versioned** model directory:

```
models/
  v1_20260403/
    best_model.json          # {"model_type": "hybrid_ensemble", "version": "v1_20260403"}
    meta.json                # training metrics, feature list, thresholds
    xgboost_model.pkl
    lightgbm_model.pkl
    rf_model.pkl
    catboost_model.cbm
    lstm_model.pt
    transformer_model.pt
    tft_model.pt
    hybrid_model.pt
    meta_learner.pkl
    imputer.pkl
    scaler.pkl
    patterns.json
    explainability.json
    candle_scaler.pkl
```

**Promotion / A/B**

- Run **old** and **new** model directories on live signals for **1 week**.
- Compare predictions and downstream outcomes; **switch** when the new model shows **&gt;5% improvement in profit factor** (or agreed primary metric) with stable drawdown characteristics.
- Record promotion decision and hashes of `meta.json` in change logs or MLOps tickets.

---

## Files

| File | Action |
|------|--------|
| `agents/backtesting/tools/preprocess.py` | Rewrite — 4 modality output |
| `agents/backtesting/tools/compute_text_embeddings.py` | New |
| `agents/backtesting/tools/train_catboost.py` | New |
| `agents/backtesting/tools/train_tft.py` | New |
| `agents/backtesting/tools/train_hybrid.py` | New |
| `agents/backtesting/tools/train_meta_learner.py` | New |
| `agents/backtesting/tools/train_lstm.py` | Rewrite — dual input |
| `agents/backtesting/tools/train_transformer.py` | Rewrite — dual input |

---

## References

- Tabular source: `enrich.py` enriched feature set.
- Candle feature list: 15 channels per bar as listed in **Candle Windows** above.
- Text encoder: `sentence-transformers/all-MiniLM-L6-v2` (384-dim output).
