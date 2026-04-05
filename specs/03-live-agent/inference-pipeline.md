# Spec: Live Inference Pipeline

## Purpose

When the Discord listener detects a trade signal, the inference pipeline enriches it with real-time market data, runs the trained classifier, checks explainability and pattern matches, and produces a go/no-go decision.

## Pipeline Flow

```
Discord Signal
  │
  ├── 1. Parse signal (Python, no tokens)
  ├── 2. Enrich with live market data (Python, API calls)
  ├── 3. Run trained classifier (Python, model.predict())
  ├── 4. Check pattern matches (Python, rules engine)
  ├── 5. Run risk checks (Python, portfolio state)
  │
  ▼
  Decision: TRADE or SKIP
  │
  ├── TRADE → Robinhood execution + log + report
  └── SKIP → Log reason + report
```

## Step 1: Parse Signal

Reuse `signal_filter.py` for quick extraction, then use `signal_parser.py` for full parsing:

```python
def parse_signal_full(content, posted_at):
    quick = parse_quick_signal(content)
    if not quick or quick['type'] == 'noise':
        return None
    
    full = fix_and_parse(content, posted_at)
    return {
        'ticker': full.ticker,
        'side': 'long' if full.signal_type == 'buy_signal' else 'short',
        'price': full.price,
        'strike': full.strike,
        'expiry': full.expiry,
        'option_type': full.option_type,
        'target': full.target,
        'stop_loss': full.stop_loss,
        'raw_message': content,
    }
```

## Step 2: Real-Time Enrichment

```python
# agents/live-template/tools/enrich_single.py

def enrich_single_trade(signal: dict) -> pd.Series:
    """Enrich a single trade signal with current market attributes.
    
    Uses the same 200 attributes as backtesting, but with live data.
    """
    ticker = signal['ticker']
    now = datetime.utcnow()
    
    # Download recent price data (60 days for indicators)
    hist = yf.download(ticker, period='3mo', interval='1d')
    
    row = {}
    
    # Price action
    row['close_1d'] = hist['Close'].iloc[-2]
    row['return_1d'] = (hist['Close'].iloc[-1] - hist['Close'].iloc[-2]) / hist['Close'].iloc[-2]
    # ... all 200 attributes computed same as enrichment step
    
    # Apply saved imputer and scaler
    imputer = joblib.load('models/imputer.pkl')
    scaler = joblib.load('models/scaler.pkl')
    
    feature_df = pd.DataFrame([row])
    feature_df = pd.DataFrame(imputer.transform(feature_df), columns=feature_df.columns)
    feature_scaled = scaler.transform(feature_df)
    
    return feature_scaled, row
```

## Step 3: Run Classifier

```python
# agents/live-template/tools/inference.py

def predict_trade(features_scaled, raw_features):
    """Run the trained classifier on enriched features."""
    model = joblib.load('models/best_classifier.pkl')
    metadata = json.load(open('models/model_metadata.json'))
    
    prediction = model.predict(features_scaled)[0]
    
    if hasattr(model, 'predict_proba'):
        confidence = model.predict_proba(features_scaled)[0][1]
    else:
        confidence = float(prediction)
    
    return {
        'prediction': 'TRADE' if prediction == 1 else 'SKIP',
        'confidence': confidence,
        'model_type': metadata['model_type'],
        'model_accuracy': metadata['accuracy'],
    }
```

## Step 4: Pattern Matching

```python
def check_patterns(raw_features: dict, patterns: list) -> dict:
    """Check how many discovered patterns match the current signal."""
    matches = []
    
    for pattern in patterns:
        condition = pattern['condition']
        if evaluate_condition(condition, raw_features):
            matches.append({
                'name': pattern['name'],
                'win_rate': pattern['win_rate'],
                'avg_return': pattern['avg_return'],
            })
    
    return {
        'pattern_matches': len(matches),
        'patterns': matches,
        'avg_win_rate': np.mean([m['win_rate'] for m in matches]) if matches else 0,
        'best_pattern': matches[0]['name'] if matches else None,
    }
```

## Step 5: Risk Check

```python
def check_risk(signal, prediction, portfolio_state, config):
    """Pre-trade risk validation."""
    risk = config['risk_params']
    
    checks = {
        'confidence_ok': prediction['confidence'] >= risk['confidence_threshold'],
        'max_positions_ok': portfolio_state['open_positions'] < risk['max_concurrent_positions'],
        'daily_loss_ok': portfolio_state['daily_pnl_pct'] > -risk['max_daily_loss_pct'],
        'position_size_ok': True,  # Calculated based on portfolio value
    }
    
    approved = all(checks.values())
    
    return {
        'approved': approved,
        'checks': checks,
        'rejection_reason': next((k for k, v in checks.items() if not v), None),
    }
```

## Decision Output

```json
{
    "signal": { "ticker": "SPX", "side": "long", "price": 5950 },
    "prediction": { "result": "TRADE", "confidence": 0.78 },
    "patterns": { "matches": 3, "avg_win_rate": 0.72 },
    "risk": { "approved": true },
    "explainability": {
        "top_factors": [
            { "feature": "rsi_14", "value": 32.5, "contribution": 0.15 },
            { "feature": "vix_level", "value": 18.2, "contribution": 0.12 },
            { "feature": "volume_ratio", "value": 1.8, "contribution": 0.10 }
        ]
    },
    "decision": "EXECUTE",
    "reasoning": "Model confidence 78% exceeds threshold. 3 pattern matches with 72% avg win rate. RSI oversold, elevated volume."
}
```

## Files to Create

| File | Action |
|------|--------|
| `agents/live-template/tools/inference.py` | New |
| `agents/live-template/tools/enrich_single.py` | New |
| `agents/live-template/tools/pattern_matcher.py` | New |
| `agents/live-template/tools/risk_check.py` | New |
| `agents/live-template/tools/decision_engine.py` | New — orchestrates the full pipeline |
