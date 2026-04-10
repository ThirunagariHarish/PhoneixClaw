# Spec: Multi-Model Training Orchestration (Backtesting Step 3)

## Purpose

Train 5-6 ML models in parallel via Claude Code sub-agents, evaluate performance, select the best trade classifier, build an explainability model, and discover recurring patterns.

## Input

Enriched Parquet from Step 2: ~200 columns, `is_profitable` as the target label.

## Outputs

1. **Trade Classifier**: Best-performing model serialized as `.pkl` or `.pt`
2. **Explainability Model**: SHAP-based feature importance + decision tree surrogate
3. **Pattern Set**: Top 50-60 patterns as JSON rules
4. **Evaluation Report**: Metrics comparison across all models

## Sub-Agent Architecture

The backtesting agent spawns 6 sub-agents (Claude Code tasks), each responsible for one model:

```
Backtesting Agent (CLAUDE.md)
  ├── Sub-Agent 1: XGBoost Classifier
  ├── Sub-Agent 2: LightGBM Classifier
  ├── Sub-Agent 3: Random Forest Classifier
  ├── Sub-Agent 4: LSTM Neural Network
  ├── Sub-Agent 5: Small Transformer
  └── Sub-Agent 6: FinBERT Fine-tuned Classifier
```

Each sub-agent:
1. Reads the enriched Parquet
2. Writes its own training script (Python)
3. Runs the script, trains the model
4. Reports metrics to a shared JSON file
5. Saves model artifact to `models/` directory

## Training Protocol

### Data Splitting (Time-Series Aware)

```python
# NO random split — must be temporal to avoid leakage
train_end = data['entry_time'].quantile(0.7)   # First 70% by time
val_end = data['entry_time'].quantile(0.85)     # Next 15%

train = data[data['entry_time'] <= train_end]
val = data[(data['entry_time'] > train_end) & (data['entry_time'] <= val_end)]
test = data[data['entry_time'] > val_end]        # Last 15%
```

### Feature Preprocessing

```python
# Handle NaN columns
features = data.drop(columns=['trade_id', 'is_profitable', 'entry_message_raw', ...])
numeric_cols = features.select_dtypes(include=[np.number]).columns

# Impute missing values (median for numeric, mode for categorical)
imputer = SimpleImputer(strategy='median')
features[numeric_cols] = imputer.fit_transform(features[numeric_cols])

# Scale features
scaler = StandardScaler()
features_scaled = scaler.fit_transform(features[numeric_cols])

# Save preprocessing artifacts
joblib.dump(imputer, 'models/imputer.pkl')
joblib.dump(scaler, 'models/scaler.pkl')
```

### Model 1: XGBoost

```python
from xgboost import XGBClassifier

model = XGBClassifier(
    n_estimators=500,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    eval_metric='logloss',
    early_stopping_rounds=50,
    scale_pos_weight=len(y_train[y_train==0]) / len(y_train[y_train==1]),
)
model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
```

### Model 2: LightGBM

```python
import lightgbm as lgb

model = lgb.LGBMClassifier(
    n_estimators=500,
    max_depth=8,
    learning_rate=0.05,
    num_leaves=63,
    min_child_samples=20,
    subsample=0.8,
    colsample_bytree=0.8,
    is_unbalance=True,
)
```

### Model 3: Random Forest

```python
from sklearn.ensemble import RandomForestClassifier

model = RandomForestClassifier(
    n_estimators=500,
    max_depth=12,
    min_samples_leaf=10,
    class_weight='balanced',
    n_jobs=-1,
)
```

### Model 4: LSTM

```python
import torch
import torch.nn as nn

class TradeLSTM(nn.Module):
    def __init__(self, input_size, hidden_size=128, num_layers=2):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=0.3)
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 64),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(64, 1),
            nn.Sigmoid()
        )
    
    def forward(self, x):
        _, (hn, _) = self.lstm(x)
        return self.fc(hn[-1])
```

For LSTM, features are reshaped into sequences: for each trade, use the 10 preceding trades' features as the sequence.

### Model 5: Small Transformer

```python
class TradeTransformer(nn.Module):
    def __init__(self, d_model=128, nhead=4, num_layers=2, input_size=200):
        super().__init__()
        self.input_proj = nn.Linear(input_size, d_model)
        encoder_layer = nn.TransformerEncoderLayer(d_model, nhead, dim_feedforward=256, dropout=0.3)
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers)
        self.classifier = nn.Linear(d_model, 1)
    
    def forward(self, x):
        x = self.input_proj(x)
        x = self.transformer(x)
        return torch.sigmoid(self.classifier(x.mean(dim=1)))
```

### Model 6: FinBERT Fine-tuned

Fine-tune FinBERT on the `entry_message_raw` text + concatenated feature summary:

```python
from transformers import AutoModelForSequenceClassification, AutoTokenizer

model = AutoModelForSequenceClassification.from_pretrained(
    'ProsusAI/finbert', num_labels=2
)
# Fine-tune on: f"{entry_message_raw} | RSI:{rsi_14} MACD:{macd_histogram} VIX:{vix_level}"
```

## Evaluation Metrics

Each sub-agent reports:

```json
{
    "model_name": "xgboost",
    "accuracy": 0.72,
    "precision": 0.68,
    "recall": 0.75,
    "f1_score": 0.71,
    "auc_roc": 0.78,
    "profit_factor": 1.45,
    "sharpe_ratio": 1.2,
    "max_drawdown_pct": -12.5,
    "total_trades_predicted": 450,
    "confusion_matrix": [[120, 55], [40, 235]],
    "training_time_seconds": 180
}
```

**Selection criteria** (weighted):
- AUC-ROC: 30%
- Profit factor (simulated PnL on test set): 30%
- Sharpe ratio: 20%
- Max drawdown: 20%

## Explainability Model

After selecting the best classifier, build explainability:

```python
import shap

# SHAP values for the best model
explainer = shap.TreeExplainer(best_model)  # or DeepExplainer for neural nets
shap_values = explainer.shap_values(X_test)

# Top feature importances
feature_importance = pd.DataFrame({
    'feature': feature_names,
    'importance': np.abs(shap_values).mean(axis=0)
}).sort_values('importance', ascending=False)

# Surrogate decision tree for human-readable rules
from sklearn.tree import DecisionTreeClassifier
surrogate = DecisionTreeClassifier(max_depth=5)
surrogate.fit(X_train, best_model.predict(X_train))
```

Output: `models/explainability.json` with top 30 features and their average SHAP contribution.

## Pattern Discovery

```python
def discover_patterns(data, predictions, n_patterns=60):
    profitable = data[predictions == 1]
    
    patterns = []
    
    # Time-based patterns
    for hour in range(8, 17):
        subset = profitable[profitable['hour_of_day'] == hour]
        if len(subset) > 10:
            win_rate = subset['is_profitable'].mean()
            patterns.append({
                'name': f'hour_{hour}_entry',
                'condition': f'hour_of_day == {hour}',
                'win_rate': win_rate,
                'sample_size': len(subset),
                'avg_return': subset['pnl_pct'].mean()
            })
    
    # RSI-based patterns
    for rsi_low, rsi_high, label in [(0,30,'oversold'), (30,50,'weak'), (50,70,'strong'), (70,100,'overbought')]:
        subset = profitable[(profitable['rsi_14'] >= rsi_low) & (profitable['rsi_14'] < rsi_high)]
        if len(subset) > 10:
            patterns.append({
                'name': f'rsi_{label}',
                'condition': f'rsi_14 between {rsi_low} and {rsi_high}',
                'win_rate': subset['is_profitable'].mean(),
                'sample_size': len(subset),
                'avg_return': subset['pnl_pct'].mean()
            })
    
    # Combination patterns (interaction features)
    # ... VIX + RSI, time + volume, etc.
    
    # Sort by profitability and return top N
    patterns.sort(key=lambda p: p['win_rate'] * np.log(p['sample_size']), reverse=True)
    return patterns[:n_patterns]
```

Output: `models/patterns.json` with the top patterns.

## Tool Scripts

```
agents/backtesting/tools/
  train_xgboost.py
  train_lightgbm.py
  train_rf.py
  train_lstm.py
  train_transformer.py
  train_finbert.py
  evaluate_models.py
  build_explainability.py
  discover_patterns.py
  preprocess.py           # Shared preprocessing
```

## Files to Create

| File | Action |
|------|--------|
| `agents/backtesting/tools/train_*.py` | New — 6 model training scripts |
| `agents/backtesting/tools/evaluate_models.py` | New — compare and select best |
| `agents/backtesting/tools/build_explainability.py` | New — SHAP + surrogate tree |
| `agents/backtesting/tools/discover_patterns.py` | New — pattern mining |
| `agents/backtesting/tools/preprocess.py` | New — shared data prep |

---

## 8-Model Architecture Upgrade

### Issues with Current Architecture

1. **LSTM/Transformer windowing is broken**: Creates sequences from unrelated trade rows rather than time-series candle data
2. **No raw candle data**: Only point-in-time indicator snapshots, losing temporal information
3. **Text embeddings discarded**: Discord messages are parsed but embeddings never used in training
4. **No multi-modal fusion**: Text, time series, and tabular features never combined
5. **Missing models**: CatBoost (native categoricals) and TFT (temporal attention) absent

### 4 Data Modalities

After preprocessing, each trade produces 4 data inputs:

| Modality | Shape | Source |
|----------|-------|--------|
| Tabular | (1, ~200) | enriched numeric features (RSI, volume, VIX, etc.) |
| Candle Windows | (30, 15) | 30 bars x 15 OHLCV+indicator features per bar |
| Text Embeddings | (1, 384) | sentence-transformers `all-MiniLM-L6-v2` on raw Discord message |
| Categoricals | (1, ~10) | analyst_id, ticker, day_of_week, hour_bucket, option_type |

### New Model 7: CatBoost

```python
from catboost import CatBoostClassifier

cat_features = ['analyst_id', 'ticker', 'day_of_week', 'hour_bucket', 'option_type']

model = CatBoostClassifier(
    iterations=1000,
    depth=8,
    learning_rate=0.03,
    cat_features=cat_features,
    auto_class_weights='Balanced',
    eval_metric='AUC',
    early_stopping_rounds=50,
)
```

### New Model 8: Temporal Fusion Transformer (TFT)

```python
from pytorch_forecasting import TemporalFusionTransformer
from pytorch_forecasting.data import TimeSeriesDataSet

# Candle windows as time-varying known reals
# Tabular features as static reals
# Categoricals as static categoricals

training = TimeSeriesDataSet(
    data,
    time_idx="bar_index",
    target="is_profitable",
    group_ids=["trade_id"],
    static_categoricals=["analyst_id", "ticker"],
    static_reals=tabular_feature_names,
    time_varying_known_reals=candle_feature_names,
    max_encoder_length=30,
    max_prediction_length=1,
)

tft = TemporalFusionTransformer.from_dataset(
    training,
    hidden_size=64,
    attention_head_size=4,
    dropout=0.2,
    hidden_continuous_size=32,
    output_size=2,
    loss=CrossEntropyLoss(),
)
```

### New Model: Hybrid Ensemble (Text + Candle + Tabular)

```python
class HybridEnsemble(nn.Module):
    def __init__(self, tabular_dim=200, text_dim=384, candle_features=15, seq_len=30):
        super().__init__()
        self.candle_encoder = nn.LSTM(candle_features, 64, batch_first=True)
        self.text_proj = nn.Linear(text_dim, 64)
        self.tabular_proj = nn.Linear(tabular_dim, 64)
        self.fusion = nn.Sequential(
            nn.Linear(192, 128),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(128, 1),
            nn.Sigmoid()
        )

    def forward(self, tabular, candle_seq, text_emb):
        _, (h_candle, _) = self.candle_encoder(candle_seq)
        h_text = self.text_proj(text_emb)
        h_tabular = self.tabular_proj(tabular)
        fused = torch.cat([h_candle[-1], h_text, h_tabular], dim=1)
        return self.fusion(fused)
```

### Fixed LSTM Architecture (Dual-Input)

The corrected LSTM takes actual candle window sequences, not trade-row sequences:

```python
class CandleLSTM(nn.Module):
    def __init__(self, candle_features=15, tabular_dim=200, hidden=128, n_layers=2):
        super().__init__()
        self.lstm = nn.LSTM(candle_features, hidden, n_layers, batch_first=True, dropout=0.3)
        self.tabular_proj = nn.Linear(tabular_dim, 64)
        self.classifier = nn.Sequential(
            nn.Linear(hidden + 64, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid()
        )

    def forward(self, candle_seq, tabular):
        _, (hn, _) = self.lstm(candle_seq)
        h_tab = self.tabular_proj(tabular)
        return self.classifier(torch.cat([hn[-1], h_tab], dim=1))
```

### Fixed Transformer Architecture (Dual-Input)

```python
class CandleTransformer(nn.Module):
    def __init__(self, candle_features=15, tabular_dim=200, d_model=128, nhead=4, n_layers=2):
        super().__init__()
        self.candle_proj = nn.Linear(candle_features, d_model)
        self.pos_enc = nn.Parameter(torch.randn(1, 30, d_model))
        encoder_layer = nn.TransformerEncoderLayer(d_model, nhead, dim_feedforward=256, dropout=0.3)
        self.transformer = nn.TransformerEncoder(encoder_layer, n_layers)
        self.tabular_proj = nn.Linear(tabular_dim, 64)
        self.classifier = nn.Sequential(
            nn.Linear(d_model + 64, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid()
        )

    def forward(self, candle_seq, tabular):
        x = self.candle_proj(candle_seq) + self.pos_enc
        x = self.transformer(x)
        h_tab = self.tabular_proj(tabular)
        return self.classifier(torch.cat([x.mean(dim=1), h_tab], dim=1))
```

### Stacking Meta-Learner

After all 8 models are trained, a meta-learner combines their predictions:

```python
from sklearn.linear_model import LogisticRegression

meta_features = np.column_stack([
    xgb_proba, lgbm_proba, rf_proba, catboost_proba,
    lstm_proba, transformer_proba, tft_proba, hybrid_proba,
])
meta_model = LogisticRegression()
meta_model.fit(meta_features_train, y_train)
```

### Updated Evaluation Metrics

In addition to the existing ML metrics, add financial performance metrics:

```json
{
    "model_name": "hybrid_ensemble",
    "accuracy": 0.74,
    "precision": 0.70,
    "recall": 0.78,
    "f1_score": 0.74,
    "auc_roc": 0.82,
    "profit_factor": 1.65,
    "sharpe_ratio": 1.5,
    "max_drawdown_pct": -8.5,
    "win_rate": 0.62,
    "avg_win_pct": 12.5,
    "avg_loss_pct": -7.2,
    "expectancy": 4.12,
    "calmar_ratio": 1.76,
    "sortino_ratio": 2.1
}
```

**Updated selection criteria** (weighted):
- Profit factor: 25%
- Sharpe ratio: 20%
- AUC-ROC: 20%
- Max drawdown (inverted): 15%
- Win rate: 10%
- Sortino ratio: 10%

### Updated Tool Scripts

```
agents/backtesting/tools/
  train_xgboost.py           # Tabular
  train_lightgbm.py          # Tabular
  train_rf.py                # Tabular
  train_catboost.py          # Tabular + native categoricals (NEW)
  train_lstm.py              # Candle windows + tabular (FIXED)
  train_transformer.py       # Candle windows + tabular (FIXED)
  train_tft.py               # All modalities via TFT (NEW)
  train_hybrid.py            # Multi-modal fusion (NEW)
  train_meta_learner.py      # Stacking ensemble (NEW)
  evaluate_models.py         # Updated with financial metrics
  build_explainability.py
  discover_patterns.py
  preprocess.py              # Rewritten for 4 modalities
  compute_text_embeddings.py # sentence-transformers (NEW)
```
