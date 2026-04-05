# Spec: Technical Analysis Skills

## Purpose

Python tools that perform technical analysis on underlying securities and options contracts to support the live agent’s trade and position-management decisions. The stack is **local computation only**: indicators, levels, and pattern heuristics are derived from downloaded OHLCV data and chain fields, not from paid charting APIs or third-party “TA as a service” products.

Goals:

- Provide a **single entry point** for a full underlying snapshot (`analyze_underlying`) used when evaluating signals and position context.
- Expose **small, testable primitives** (RSI, MACD, ADX, etc.) so the agent and tests can reuse logic without duplicating formulas.
- Support **options-aware** workflows via Greeks, implied volatility, max pain, and simple risk metrics, aligned with chain data available from the broker integration.
- Feed **structured dict outputs** into the decision engine and position monitor (quick vs full scans) with explicit rules for trim, take-profit, hold, and close.

---

## Data Source Mapping

| Concern | Source | Notes |
|--------|--------|--------|
| Underlying price history | **yfinance** (`yfinance` / `yf.download`) | Daily bars and intraday **1m** and **5m** candles as needed. All TA and pattern logic consumes this `pd.DataFrame` (Open, High, Low, Close, Volume). |
| Options chain (IV, Greeks, bid/ask, OI, volume) | **robin_stocks** (options chain), surfaced via **Robinhood MCP** where applicable | Broker chain is authoritative for listed greeks and IV when available; Black–Scholes functions below apply when solving for IV or cross-checking. |
| Charting / indicators | **None (paid or external)** | No TradingView, TrendSpider, or similar. Every indicator and pattern is computed locally from raw candles. |

Conventions:

- `hist` columns: at minimum `Open`, `High`, `Low`, `Close`, `Volume` (case as returned by yfinance; normalize inside tools if required).
- Timezone and session boundaries should be documented in implementation; intraday scans should use consistent bar alignment for the chosen `interval`.

---

## `technical_analysis.py` — Full Function Signatures

### Entry point

```python
def analyze_underlying(ticker: str, interval: str = "1d") -> dict:
    """Full TA snapshot for decision support.

    Fetches history for `ticker` at `interval` (e.g. '1d', '5m', '1m'),
    then aggregates trend, momentum, volatility, volume, levels, and patterns
    into one structured dict suitable for the live agent.
    """
```

The returned `dict` should align with the following logical sections (field names may be nested as in the reference below):

- **trend**: direction, strength (e.g. ADX), `sma_alignment` from `check_sma_alignment`
- **momentum**: `rsi`, `macd`, `stochastic`
- **volatility**: `atr`, `bb_width`; IV rank (if derived from chain/MCP) may live here or under a separate key documented in integration
- **volume**: relative volume, `obv_trend` / OBV slope
- **levels**: support, resistance, pivot points
- **patterns**: result of `detect_chart_patterns`

### Indicator and level primitives

```python
def calculate_rsi(hist: pd.DataFrame, period: int = 14) -> float:
    """Wilder-style RSI on `Close`; return last value."""

def calculate_macd(hist: pd.DataFrame) -> dict:
    """MACD(12,26,9) on `Close`.

    Returns e.g. {
        'signal': float,      # MACD line vs signal interpretation or raw line
        'histogram': float,   # last histogram bar
        'trend': str,         # e.g. 'bullish' | 'bearish' | 'neutral' per rule set
    }
    (Exact keys fixed at implementation time; must include signal, histogram, trend.)
    """

def calculate_adx(hist: pd.DataFrame, period: int = 14) -> float:
    """Average Directional Index; return last ADX value."""

def calculate_atr(hist: pd.DataFrame, period: int = 14) -> float:
    """Average True Range; return last ATR."""

def calculate_bb_width(hist: pd.DataFrame, period: int = 20) -> dict:
    """Bollinger Bands on `Close` (typical std multiplier 2).

    Returns {
        'upper': float,
        'lower': float,
        'width': float,   # (upper - lower) / middle or absolute per spec in code
        'pct_b': float,   # %B for last bar
    }
    """

def calculate_stochastic(
    hist: pd.DataFrame,
    k_period: int = 14,
    d_period: int = 3,
) -> dict:
    """Stochastic oscillator; returns last-bar %K and %D (and any raw series keys if needed)."""

def check_sma_alignment(hist: pd.DataFrame) -> str:
    """Compare short/medium/long SMA stack (e.g. 20/50/200 on `Close`).

    Returns exactly one of: 'bullish_stack', 'bearish_stack', 'mixed'.
    """

def calculate_obv_slope(hist: pd.DataFrame, window: int = 10) -> float:
    """On-Balance Volume slope over the last `window` bars (e.g. linear regression or delta/window)."""
```

### Level detection

```python
def find_support_levels(hist: pd.DataFrame, window: int = 20) -> list[float]:
    """Local minima / swing-low derived support prices (most recent first or sorted ascending; document in impl)."""

def find_resistance_levels(hist: pd.DataFrame, window: int = 20) -> list[float]:
    """Local maxima / swing-high derived resistance prices."""

def calculate_pivots(hist: pd.DataFrame) -> dict:
    """Standard pivot from prior period H/L/C.

    Returns {
        'pivot': float,
        'r1': float, 'r2': float, 'r3': float,
        's1': float, 's2': float, 's3': float,
    }
    """
```

---

## Chart Pattern Detection

```python
def detect_chart_patterns(hist: pd.DataFrame) -> list[dict]:
    """Geometric / rule-based pattern tags from swing structure."""
```

### Supported patterns

- `double_top`
- `double_bottom`
- `head_and_shoulders`
- `inverse_h_and_s`
- `bull_flag`
- `bear_flag`
- `ascending_triangle`
- `descending_triangle`
- `wedge` (rising or falling; encode in `pattern` string or nested detail if needed)

### Return shape (each list element)

```python
{
    "pattern": str,           # one of the names above (or sub-variant as agreed)
    "confidence": float,      # 0.0–1.0 heuristic score
    "target_price": float,    # measured move or pattern-implied objective
}
```

### Detection method

1. **Swing identification**: detect swing highs and swing lows (e.g. fractal or rolling window extrema on `High` / `Low`).
2. **Geometric rule matching**: encode each pattern as tolerances on distances, slopes, symmetry, and number of touches between swings.
3. **Ranking**: emit only patterns that pass minimum rules; sort by `confidence` descending when multiple match.

---

## `options_analysis.py` — Full Function Signatures

### Contract analysis

```python
def analyze_option(
    ticker: str,
    strike: float,
    expiry,  # date or ISO str; type fixed in implementation
    option_type: str,  # 'call' | 'put'
) -> dict:
    """Load chain (robin_stocks / MCP), locate contract, merge broker greeks with BS where needed.

    Return structure includes greeks, pricing, positioning (OI, volume, max_pain), and risk fields.
    """
```

### Black–Scholes Greeks

Assume standard notation: `S` spot, `K` strike, `T` time to expiry in years, `r` risk-free rate, `sigma` implied vol, `option_type` call/put.

```python
def calculate_delta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    ...

def calculate_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    ...

def calculate_theta(S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> float:
    ...

def calculate_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    ...
```

### Implied volatility

```python
def calculate_iv(
    option_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: str,
) -> float:
    """Solve for sigma such that BS price matches `option_price` using Newton–Raphson (with bounds and fallbacks)."""
```

### Chain and position metrics

```python
def calculate_max_pain(chain: pd.DataFrame) -> float:
    """Strike at which combined option intrinsic value for open interest is minimized for holders (document column names for chain)."""

def calculate_prob_itm(S: float, K: float, sigma: float, T: float) -> float:
    """Risk-neutral or lognormal ITM probability (document formula: e.g. Black–Scholes d2)."""

def calculate_breakeven(strike: float, premium: float, option_type: str) -> float:
    """Underlying level at expiration for zero P/L at contract level."""

def calculate_risk_reward(contract, underlying_price: float) -> float:
    """Ratio of expected/representative reward to risk for the position; `contract` is dict or row with bid/ask/strike/type (spec precise fields in impl)."""
```

---

## Integration with Position Monitoring

### Lightweight vs comprehensive scans

```python
def quick_ta_check(ticker: str) -> dict:
    """Lightweight check on ~1m data: last price vs stop, target, trailing stop flags.

    Minimal indicators only; fast path for “is the position still valid right now?”
    """

def full_ta_scan(ticker: str) -> dict:
    """Comprehensive scan on ~5m (and/or daily context): full indicator set + levels + patterns
    for hold vs close decisions. May delegate to `analyze_underlying` with appropriate intervals.
    """
```

### How TA output feeds the decision engine

| Condition | Intended signal |
|-----------|------------------|
| RSI > 70 **and** MACD weakening (histogram contracting / bearish cross) | **Trim** or reduce position size |
| Price at / near **resistance** **and** volume declining vs recent average | **Take profit** or tighten stops |
| Break **below** identified support (close confirmed on timeframe in use) | **Close** position promptly |
| Strong trend continuation (e.g. ADX elevated, SMA alignment favorable) **and** volume confirming | **Hold** or favor continuation |

Rules should be implemented as a thin policy layer that reads the dicts from `quick_ta_check` / `full_ta_scan` (and optional `analyze_underlying`) rather than burying trading logic inside each indicator function.

---

## Files to Create

| File | Action | Description |
|------|--------|-------------|
| `agents/live-template/tools/technical_analysis.py` | New | Full TA engine: yfinance ingestion, indicators, levels, patterns, `analyze_underlying`, `quick_ta_check`, `full_ta_scan`. |
| `agents/live-template/tools/options_analysis.py` | New | Options chain integration, Greeks (BS + broker), IV solver, max pain, breakeven, prob ITM, risk/reward, `analyze_option`. |
