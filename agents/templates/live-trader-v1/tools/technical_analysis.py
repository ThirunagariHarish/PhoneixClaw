"""Full technical analysis engine: multi-timeframe TA with pattern detection.

Usage:
    python technical_analysis.py --ticker SPX --output ta_result.json
"""

import argparse
import json
import logging
import sys
import warnings
from datetime import datetime, timezone

import numpy as np

warnings.filterwarnings("ignore")

try:
    import pandas as pd
except ImportError:
    print("pandas is required: pip install pandas", file=sys.stderr)
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    yf = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ta] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Indicator functions
# ---------------------------------------------------------------------------

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _bollinger(close: pd.Series, window: int = 20, num_std: int = 2):
    mid = _sma(close, window)
    std = close.rolling(window).std()
    return mid + num_std * std, mid, mid - num_std * std


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    atr_vals = _atr(high, low, close, period)
    plus_di = 100 * _ema(plus_dm, period) / atr_vals.replace(0, np.nan)
    minus_di = 100 * _ema(minus_dm, period) / atr_vals.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_val = _ema(dx, period)
    return adx_val, plus_di, minus_di


def _stochastic_rsi(close: pd.Series, rsi_period: int = 14, stoch_period: int = 14,
                    k_smooth: int = 3, d_smooth: int = 3):
    rsi_vals = _rsi(close, rsi_period)
    lowest = rsi_vals.rolling(stoch_period).min()
    highest = rsi_vals.rolling(stoch_period).max()
    stoch_rsi = (rsi_vals - lowest) / (highest - lowest).replace(0, np.nan)
    k = stoch_rsi.rolling(k_smooth).mean() * 100
    d = k.rolling(d_smooth).mean()
    return k, d


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    return (np.sign(close.diff()) * volume).fillna(0).cumsum()


def _last(series: pd.Series) -> float:
    if series is None or series.empty:
        return np.nan
    val = series.iloc[-1]
    return float(val) if pd.notna(val) else np.nan


# ---------------------------------------------------------------------------
# Support / Resistance detection
# ---------------------------------------------------------------------------

def _find_local_extrema(series: pd.Series, order: int = 5) -> tuple[list, list]:
    """Find local minima and maxima using a rolling window comparison."""
    maxima_idx = []
    minima_idx = []
    values = series.values
    for i in range(order, len(values) - order):
        window = values[i - order: i + order + 1]
        if values[i] == np.max(window):
            maxima_idx.append(i)
        if values[i] == np.min(window):
            minima_idx.append(i)
    return maxima_idx, minima_idx


def _support_resistance(close: pd.Series, high: pd.Series, low: pd.Series,
                        num_levels: int = 5) -> dict:
    """Identify support and resistance levels from local extrema clustering."""
    maxima_idx, minima_idx = _find_local_extrema(close, order=10)

    resistance_prices = sorted([float(high.iloc[i]) for i in maxima_idx if i < len(high)], reverse=True)
    support_prices = sorted([float(low.iloc[i]) for i in minima_idx if i < len(low)])

    def _cluster(prices: list[float], tolerance: float = 0.02) -> list[dict]:
        if not prices:
            return []
        clusters: list[list[float]] = []
        current_cluster = [prices[0]]
        for p in prices[1:]:
            if abs(p - current_cluster[-1]) / current_cluster[-1] <= tolerance:
                current_cluster.append(p)
            else:
                clusters.append(current_cluster)
                current_cluster = [p]
        clusters.append(current_cluster)
        levels = [{"price": round(np.mean(c), 2), "touches": len(c), "strength": len(c)}
                  for c in clusters]
        levels.sort(key=lambda x: x["strength"], reverse=True)
        return levels[:num_levels]

    current_price = float(close.iloc[-1])
    r_levels = _cluster([p for p in resistance_prices if p > current_price * 0.99])
    s_levels = _cluster([p for p in support_prices if p < current_price * 1.01])

    nearest_resistance = r_levels[0]["price"] if r_levels else None
    nearest_support = s_levels[0]["price"] if s_levels else None

    return {
        "resistance_levels": r_levels,
        "support_levels": s_levels,
        "nearest_resistance": nearest_resistance,
        "nearest_support": nearest_support,
        "distance_to_resistance_pct": round((nearest_resistance - current_price) / current_price * 100, 3) if nearest_resistance else None,
        "distance_to_support_pct": round((current_price - nearest_support) / current_price * 100, 3) if nearest_support else None,
    }


# ---------------------------------------------------------------------------
# Pattern detection
# ---------------------------------------------------------------------------

def _detect_patterns(close: pd.Series, high: pd.Series, low: pd.Series) -> list[dict]:
    """Detect chart patterns via local min/max analysis."""
    patterns = []
    maxima_idx, minima_idx = _find_local_extrema(close, order=5)

    if len(close) < 30:
        return patterns

    maxima_prices = [(i, float(close.iloc[i])) for i in maxima_idx]
    minima_prices = [(i, float(close.iloc[i])) for i in minima_idx]

    # Double Top: two highs at similar level with a valley between
    for i in range(len(maxima_prices) - 1):
        idx1, p1 = maxima_prices[i]
        idx2, p2 = maxima_prices[i + 1]
        if idx2 - idx1 < 5:
            continue
        tolerance = 0.02 * max(p1, p2)
        if abs(p1 - p2) <= tolerance:
            valley = float(close.iloc[idx1:idx2 + 1].min())
            neckline = valley
            current = float(close.iloc[-1])
            if current < neckline:
                patterns.append({
                    "pattern": "double_top",
                    "signal": "bearish",
                    "confidence": round(1 - abs(p1 - p2) / max(p1, p2), 3),
                    "neckline": round(neckline, 2),
                    "peak": round(max(p1, p2), 2),
                })
            elif abs(p1 - p2) / max(p1, p2) < 0.01:
                patterns.append({
                    "pattern": "double_top_forming",
                    "signal": "bearish_warning",
                    "confidence": round(1 - abs(p1 - p2) / max(p1, p2), 3),
                    "neckline": round(neckline, 2),
                    "peak": round(max(p1, p2), 2),
                })

    # Double Bottom: two lows at similar level with a peak between
    for i in range(len(minima_prices) - 1):
        idx1, p1 = minima_prices[i]
        idx2, p2 = minima_prices[i + 1]
        if idx2 - idx1 < 5:
            continue
        tolerance = 0.02 * max(p1, p2)
        if abs(p1 - p2) <= tolerance:
            peak = float(close.iloc[idx1:idx2 + 1].max())
            neckline = peak
            current = float(close.iloc[-1])
            if current > neckline:
                patterns.append({
                    "pattern": "double_bottom",
                    "signal": "bullish",
                    "confidence": round(1 - abs(p1 - p2) / max(p1, p2), 3),
                    "neckline": round(neckline, 2),
                    "trough": round(min(p1, p2), 2),
                })
            elif abs(p1 - p2) / max(p1, p2) < 0.01:
                patterns.append({
                    "pattern": "double_bottom_forming",
                    "signal": "bullish_warning",
                    "confidence": round(1 - abs(p1 - p2) / max(p1, p2), 3),
                    "neckline": round(neckline, 2),
                    "trough": round(min(p1, p2), 2),
                })

    # Head and Shoulders: three peaks where middle is highest
    for i in range(len(maxima_prices) - 2):
        idx1, p1 = maxima_prices[i]
        idx2, p2 = maxima_prices[i + 1]
        idx3, p3 = maxima_prices[i + 2]
        if idx3 - idx1 < 10:
            continue
        if p2 > p1 and p2 > p3 and abs(p1 - p3) / max(p1, p3) < 0.03:
            valleys_between = [float(close.iloc[j]) for j in range(idx1, idx3 + 1)
                               if j in minima_idx]
            if len(valleys_between) >= 2:
                neckline = np.mean(valleys_between[:2])
            elif valleys_between:
                neckline = valleys_between[0]
            else:
                neckline = float(close.iloc[idx1:idx3 + 1].min())
            current = float(close.iloc[-1])
            if current < neckline:
                patterns.append({
                    "pattern": "head_and_shoulders",
                    "signal": "bearish",
                    "confidence": round(min(1.0, p2 / max(p1, p3) - 0.95), 3),
                    "neckline": round(neckline, 2),
                    "head": round(p2, 2),
                    "left_shoulder": round(p1, 2),
                    "right_shoulder": round(p3, 2),
                })

    # Inverse Head and Shoulders
    for i in range(len(minima_prices) - 2):
        idx1, p1 = minima_prices[i]
        idx2, p2 = minima_prices[i + 1]
        idx3, p3 = minima_prices[i + 2]
        if idx3 - idx1 < 10:
            continue
        if p2 < p1 and p2 < p3 and abs(p1 - p3) / max(p1, p3) < 0.03:
            peaks_between = [float(close.iloc[j]) for j in range(idx1, idx3 + 1)
                             if j in maxima_idx]
            if len(peaks_between) >= 2:
                neckline = np.mean(peaks_between[:2])
            elif peaks_between:
                neckline = peaks_between[0]
            else:
                neckline = float(close.iloc[idx1:idx3 + 1].max())
            current = float(close.iloc[-1])
            if current > neckline:
                patterns.append({
                    "pattern": "inverse_head_and_shoulders",
                    "signal": "bullish",
                    "confidence": round(min(1.0, max(p1, p3) / p2 - 0.95), 3),
                    "neckline": round(neckline, 2),
                    "head": round(p2, 2),
                    "left_shoulder": round(p1, 2),
                    "right_shoulder": round(p3, 2),
                })

    return patterns


# ---------------------------------------------------------------------------
# Timeframe analysis
# ---------------------------------------------------------------------------

def _safe_download(ticker: str, period: str, interval: str) -> pd.DataFrame:
    if yf is None:
        raise RuntimeError("yfinance not installed")
    data = yf.download(ticker, period=period, interval=interval, progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    return data


def _analyze_timeframe(hist: pd.DataFrame, label: str) -> dict:
    """Run full indicator suite on a single timeframe."""
    if hist.empty or len(hist) < 20:
        return {"timeframe": label, "error": "insufficient_data", "bars": len(hist)}

    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]

    signals = []
    indicators = {}

    # RSI
    rsi_val = _last(_rsi(close, 14))
    indicators["rsi_14"] = round(rsi_val, 2) if pd.notna(rsi_val) else None
    if pd.notna(rsi_val):
        if rsi_val < 30:
            signals.append({"name": "rsi_oversold", "direction": "bullish", "value": rsi_val})
        elif rsi_val > 70:
            signals.append({"name": "rsi_overbought", "direction": "bearish", "value": rsi_val})
        elif rsi_val < 50:
            signals.append({"name": "rsi_below_50", "direction": "bearish", "value": rsi_val})
        else:
            signals.append({"name": "rsi_above_50", "direction": "bullish", "value": rsi_val})

    # MACD
    macd_line, macd_sig, macd_hist = _macd(close, 12, 26, 9)
    indicators["macd_line"] = round(_last(macd_line), 4) if pd.notna(_last(macd_line)) else None
    indicators["macd_signal"] = round(_last(macd_sig), 4) if pd.notna(_last(macd_sig)) else None
    indicators["macd_histogram"] = round(_last(macd_hist), 4) if pd.notna(_last(macd_hist)) else None
    if len(macd_line) >= 2 and pd.notna(macd_line.iloc[-1]) and pd.notna(macd_sig.iloc[-1]):
        if macd_line.iloc[-1] > macd_sig.iloc[-1] and macd_line.iloc[-2] <= macd_sig.iloc[-2]:
            signals.append({"name": "macd_bullish_cross", "direction": "bullish", "value": _last(macd_hist)})
        elif macd_line.iloc[-1] < macd_sig.iloc[-1] and macd_line.iloc[-2] >= macd_sig.iloc[-2]:
            signals.append({"name": "macd_bearish_cross", "direction": "bearish", "value": _last(macd_hist)})
        elif macd_line.iloc[-1] > macd_sig.iloc[-1]:
            signals.append({"name": "macd_bullish", "direction": "bullish", "value": _last(macd_hist)})
        else:
            signals.append({"name": "macd_bearish", "direction": "bearish", "value": _last(macd_hist)})

    # Bollinger Bands
    bb_upper, bb_mid, bb_lower = _bollinger(close, 20, 2)
    indicators["bb_upper"] = round(_last(bb_upper), 2) if pd.notna(_last(bb_upper)) else None
    indicators["bb_middle"] = round(_last(bb_mid), 2) if pd.notna(_last(bb_mid)) else None
    indicators["bb_lower"] = round(_last(bb_lower), 2) if pd.notna(_last(bb_lower)) else None
    if pd.notna(_last(bb_upper)) and pd.notna(_last(bb_lower)):
        price = float(close.iloc[-1])
        if price >= _last(bb_upper):
            signals.append({"name": "bb_upper_touch", "direction": "bearish", "value": price})
        elif price <= _last(bb_lower):
            signals.append({"name": "bb_lower_touch", "direction": "bullish", "value": price})
        bb_pos = (price - _last(bb_lower)) / (_last(bb_upper) - _last(bb_lower))
        indicators["bb_position"] = round(bb_pos, 3) if pd.notna(bb_pos) else None
        bb_w = (_last(bb_upper) - _last(bb_lower)) / _last(bb_mid) if _last(bb_mid) else None
        indicators["bb_width"] = round(bb_w, 4) if bb_w and pd.notna(bb_w) else None

    # ADX
    adx_val, plus_di, minus_di = _adx(high, low, close, 14)
    indicators["adx_14"] = round(_last(adx_val), 2) if pd.notna(_last(adx_val)) else None
    indicators["plus_di"] = round(_last(plus_di), 2) if pd.notna(_last(plus_di)) else None
    indicators["minus_di"] = round(_last(minus_di), 2) if pd.notna(_last(minus_di)) else None
    if pd.notna(_last(adx_val)):
        if _last(adx_val) > 25:
            if pd.notna(_last(plus_di)) and pd.notna(_last(minus_di)):
                if _last(plus_di) > _last(minus_di):
                    signals.append({"name": "adx_strong_trend_up", "direction": "bullish", "value": _last(adx_val)})
                else:
                    signals.append({"name": "adx_strong_trend_down", "direction": "bearish", "value": _last(adx_val)})
        else:
            signals.append({"name": "adx_weak_trend", "direction": "neutral", "value": _last(adx_val)})

    # Stochastic RSI
    srsi_k, srsi_d = _stochastic_rsi(close)
    indicators["stoch_rsi_k"] = round(_last(srsi_k), 2) if pd.notna(_last(srsi_k)) else None
    indicators["stoch_rsi_d"] = round(_last(srsi_d), 2) if pd.notna(_last(srsi_d)) else None
    if pd.notna(_last(srsi_k)):
        if _last(srsi_k) < 20:
            signals.append({"name": "stoch_rsi_oversold", "direction": "bullish", "value": _last(srsi_k)})
        elif _last(srsi_k) > 80:
            signals.append({"name": "stoch_rsi_overbought", "direction": "bearish", "value": _last(srsi_k)})

    # Volume analysis
    obv_vals = _obv(close, volume)
    vol_sma = _sma(volume, 20)
    indicators["obv"] = round(_last(obv_vals), 0) if pd.notna(_last(obv_vals)) else None
    indicators["volume_last"] = float(volume.iloc[-1]) if not volume.empty else None
    indicators["volume_sma_20"] = round(_last(vol_sma), 0) if pd.notna(_last(vol_sma)) else None
    if indicators["volume_sma_20"] and indicators["volume_sma_20"] > 0:
        vol_ratio = indicators["volume_last"] / indicators["volume_sma_20"]
        indicators["volume_ratio"] = round(vol_ratio, 2)
        if vol_ratio > 2.0:
            direction = "bullish" if close.iloc[-1] > close.iloc[-2] else "bearish"
            signals.append({"name": "volume_spike", "direction": direction, "value": vol_ratio})

    if len(obv_vals) >= 10:
        obv_slope = float(obv_vals.iloc[-1] - obv_vals.iloc[-10]) / 10
        price_slope = float(close.iloc[-1] - close.iloc[-10]) / 10
        if obv_slope > 0 and price_slope < 0:
            signals.append({"name": "obv_bullish_divergence", "direction": "bullish", "value": obv_slope})
        elif obv_slope < 0 and price_slope > 0:
            signals.append({"name": "obv_bearish_divergence", "direction": "bearish", "value": obv_slope})

    # Moving average signals
    for w in [20, 50, 200]:
        sma_val = _last(_sma(close, w))
        if pd.notna(sma_val) and len(close) >= w:
            indicators[f"sma_{w}"] = round(sma_val, 2)
            if close.iloc[-1] > sma_val and close.iloc[-2] <= sma_val:
                signals.append({"name": f"price_cross_above_sma{w}", "direction": "bullish", "value": sma_val})
            elif close.iloc[-1] < sma_val and close.iloc[-2] >= sma_val:
                signals.append({"name": f"price_cross_below_sma{w}", "direction": "bearish", "value": sma_val})

    # Support / Resistance
    sr = _support_resistance(close, high, low)

    # Patterns
    detected_patterns = _detect_patterns(close, high, low) if len(close) >= 30 else []

    # Score the signals
    bullish = sum(1 for s in signals if s["direction"] == "bullish")
    bearish = sum(1 for s in signals if s["direction"] == "bearish")
    total = max(bullish + bearish, 1)

    if bullish > bearish * 1.5:
        verdict = "bullish"
    elif bearish > bullish * 1.5:
        verdict = "bearish"
    else:
        verdict = "neutral"

    return {
        "timeframe": label,
        "bars": len(hist),
        "last_close": round(float(close.iloc[-1]), 2),
        "verdict": verdict,
        "bullish_signals": bullish,
        "bearish_signals": bearish,
        "signal_ratio": round(bullish / total, 3),
        "indicators": indicators,
        "signals": signals,
        "support_resistance": sr,
        "patterns": detected_patterns,
    }


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

TICKER_MAP = {
    "SPX": "^GSPC",
    "NDX": "^NDX",
    "DJI": "^DJI",
    "VIX": "^VIX",
    "RUT": "^RUT",
}


def run_analysis(ticker: str) -> dict:
    """Run full multi-timeframe technical analysis."""
    yf_ticker = TICKER_MAP.get(ticker.upper(), ticker)
    log.info("Running TA for %s (yfinance: %s)", ticker, yf_ticker)

    timeframes = {
        "1m": {"period": "7d", "interval": "1m"},
        "5m": {"period": "60d", "interval": "5m"},
        "daily": {"period": "2y", "interval": "1d"},
    }

    results = {}
    for label, params in timeframes.items():
        try:
            hist = _safe_download(yf_ticker, params["period"], params["interval"])
            results[label] = _analyze_timeframe(hist, label)
            log.info("  %s: %d bars, verdict=%s", label, len(hist), results[label].get("verdict", "N/A"))
        except Exception as exc:
            log.warning("  %s failed: %s", label, exc)
            results[label] = {"timeframe": label, "error": str(exc)}

    verdicts = [r.get("verdict") for r in results.values() if r.get("verdict")]
    bullish_count = verdicts.count("bullish")
    bearish_count = verdicts.count("bearish")

    if bullish_count > bearish_count:
        overall = "bullish"
    elif bearish_count > bullish_count:
        overall = "bearish"
    else:
        overall = "neutral"

    all_signals = []
    for r in results.values():
        for s in r.get("signals", []):
            s_copy = dict(s)
            s_copy["timeframe"] = r.get("timeframe")
            if isinstance(s_copy.get("value"), float):
                s_copy["value"] = round(s_copy["value"], 4)
            all_signals.append(s_copy)

    all_patterns = []
    for r in results.values():
        for p in r.get("patterns", []):
            p_copy = dict(p)
            p_copy["timeframe"] = r.get("timeframe")
            all_patterns.append(p_copy)

    total_bull = sum(r.get("bullish_signals", 0) for r in results.values())
    total_bear = sum(r.get("bearish_signals", 0) for r in results.values())
    total = max(total_bull + total_bear, 1)
    confidence = abs(total_bull - total_bear) / total

    return {
        "ticker": ticker,
        "yfinance_ticker": yf_ticker,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_verdict": overall,
        "confidence": round(confidence, 3),
        "bullish_signals_total": total_bull,
        "bearish_signals_total": total_bear,
        "timeframes": results,
        "all_signals": all_signals,
        "all_patterns": all_patterns,
    }


def _json_safe(obj):
    """Convert numpy types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        return None if np.isnan(obj) else round(float(obj), 6)
    if isinstance(obj, (np.integer, np.int64)):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return obj


def main():
    parser = argparse.ArgumentParser(description="Full technical analysis engine")
    parser.add_argument("--ticker", required=True, help="Ticker symbol (e.g. SPX, AAPL)")
    parser.add_argument("--output", default="ta_result.json", help="Output JSON path")
    args = parser.parse_args()

    if yf is None:
        log.error("yfinance is required: pip install yfinance")
        sys.exit(1)

    result = run_analysis(args.ticker)
    result = _json_safe(result)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(json.dumps({
        "status": "ok",
        "ticker": args.ticker,
        "verdict": result["overall_verdict"],
        "confidence": result["confidence"],
        "bullish": result["bullish_signals_total"],
        "bearish": result["bearish_signals_total"],
        "patterns": len(result["all_patterns"]),
        "output": args.output,
    }))


if __name__ == "__main__":
    main()
