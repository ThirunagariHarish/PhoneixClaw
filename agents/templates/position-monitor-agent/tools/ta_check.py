"""Technical analysis check for position monitoring.

Computes 15+ indicators and context signals, scoring how 'exitable' a position is.
Each indicator contributes a weighted urgency score. Weights are tunable via config.

Usage:
    python ta_check.py --ticker AAPL --side buy --output ta.json
    python ta_check.py --ticker AAPL --side buy --config config.json --output ta.json
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

DEFAULT_WEIGHTS = {
    "rsi": 20,
    "macd": 10,
    "bollinger": 15,
    "support_resistance": 10,
    "adx": 8,
    "cci": 8,
    "stochastic": 8,
    "mfi": 8,
    "obv": 6,
    "williams_r": 6,
    "keltner": 8,
    "ichimoku": 10,
    "vwap": 8,
    "volume_zscore": 10,
    "atr_trailing": 12,
    "spy_context": 8,
    "vix_context": 10,
}


def compute_ta(ticker: str, side: str, config: dict | None = None) -> dict:
    """Compute 15+ TA indicators and exit urgency score for a position."""
    weights = {**DEFAULT_WEIGHTS}
    if config and "ta_weights" in config:
        weights.update(config["ta_weights"])

    result = {
        "ticker": ticker,
        "side": side,
        "exit_urgency": 0,
        "indicators": {},
        "signals": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        import yfinance as yf

        data = yf.download(ticker, period="5d", interval="5m", progress=False)
        if data.empty or len(data) < 30:
            result["error"] = "insufficient data"
            return result
        if hasattr(data.columns, "levels"):
            data.columns = data.columns.get_level_values(0)

        close = data["Close"].astype(float)
        high = data["High"].astype(float)
        low = data["Low"].astype(float)
        volume = data["Volume"].astype(float)
        current_price = float(close.iloc[-1])
        result["indicators"]["current_price"] = round(current_price, 2)
        urgency = 0

        is_long = side == "buy"

        # 1. RSI(14)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        current_rsi = float(rsi.iloc[-1])
        result["indicators"]["rsi_14"] = round(current_rsi, 1)
        if is_long and current_rsi > 75:
            urgency += weights["rsi"]
            result["signals"]["rsi"] = "overbought"
        elif not is_long and current_rsi < 25:
            urgency += weights["rsi"]
            result["signals"]["rsi"] = "oversold"

        # 2. MACD(12/26/9)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = float(macd_line.iloc[-1] - signal_line.iloc[-1])
        result["indicators"]["macd_histogram"] = round(macd_hist, 4)
        if is_long and macd_hist < 0:
            urgency += weights["macd"]
            result["signals"]["macd"] = "bearish_cross"
        elif not is_long and macd_hist > 0:
            urgency += weights["macd"]
            result["signals"]["macd"] = "bullish_cross"

        # 3. Bollinger Bands(20, 2σ)
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_upper = float((sma20 + 2 * std20).iloc[-1])
        bb_lower = float((sma20 - 2 * std20).iloc[-1])
        result["indicators"]["bb_upper"] = round(bb_upper, 2)
        result["indicators"]["bb_lower"] = round(bb_lower, 2)
        if is_long and current_price >= bb_upper:
            urgency += weights["bollinger"]
            result["signals"]["bollinger"] = "above_upper_band"
        elif not is_long and current_price <= bb_lower:
            urgency += weights["bollinger"]
            result["signals"]["bollinger"] = "below_lower_band"

        # 4. Support/Resistance (20-bar high/low)
        recent_high = float(high.iloc[-20:].max())
        recent_low = float(low.iloc[-20:].min())
        result["indicators"]["resistance"] = round(recent_high, 2)
        result["indicators"]["support"] = round(recent_low, 2)
        if is_long and current_price >= recent_high * 0.98:
            urgency += weights["support_resistance"]
            result["signals"]["sr"] = "near_resistance"
        elif not is_long and current_price <= recent_low * 1.02:
            urgency += weights["sr"]
            result["signals"]["sr"] = "near_support"

        # 5. ADX(14) — trend strength
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
        prev_close = close.shift(1)
        tr = np.maximum(high - low, np.maximum((high - prev_close).abs(), (low - prev_close).abs()))
        atr_14 = tr.rolling(14).mean()
        plus_di = 100 * plus_dm.ewm(span=14, adjust=False).mean() / atr_14.replace(0, np.nan)
        minus_di = 100 * minus_dm.ewm(span=14, adjust=False).mean() / atr_14.replace(0, np.nan)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(span=14, adjust=False).mean()
        current_adx = float(adx.iloc[-1])
        result["indicators"]["adx_14"] = round(current_adx, 1)
        if current_adx > 25:
            if (is_long and float(minus_di.iloc[-1]) > float(plus_di.iloc[-1])) or \
               (not is_long and float(plus_di.iloc[-1]) > float(minus_di.iloc[-1])):
                urgency += weights["adx"]
                result["signals"]["adx"] = "strong_adverse_trend"

        # 6. CCI(20)
        tp = (high + low + close) / 3
        tp_sma = tp.rolling(20).mean()
        tp_mad = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
        cci = (tp - tp_sma) / (0.015 * tp_mad.replace(0, np.nan))
        current_cci = float(cci.iloc[-1])
        result["indicators"]["cci_20"] = round(current_cci, 1)
        if is_long and current_cci > 100:
            urgency += weights["cci"]
            result["signals"]["cci"] = "overbought"
        elif not is_long and current_cci < -100:
            urgency += weights["cci"]
            result["signals"]["cci"] = "oversold"

        # 7. Stochastic(14,3)
        lowest_14 = low.rolling(14).min()
        highest_14 = high.rolling(14).max()
        stoch_k = 100 * (close - lowest_14) / (highest_14 - lowest_14).replace(0, np.nan)
        stoch_d = stoch_k.rolling(3).mean()
        current_k = float(stoch_k.iloc[-1])
        result["indicators"]["stoch_k"] = round(current_k, 1)
        result["indicators"]["stoch_d"] = round(float(stoch_d.iloc[-1]), 1)
        if is_long and current_k > 80:
            urgency += weights["stochastic"]
            result["signals"]["stochastic"] = "overbought"
        elif not is_long and current_k < 20:
            urgency += weights["stochastic"]
            result["signals"]["stochastic"] = "oversold"

        # 8. MFI(14) — volume-weighted RSI
        tp_v = tp * volume
        pos_flow = tp_v.where(tp.diff() > 0, 0.0).rolling(14).sum()
        neg_flow = tp_v.where(tp.diff() <= 0, 0.0).rolling(14).sum()
        mfi = 100 - (100 / (1 + pos_flow / neg_flow.replace(0, np.nan)))
        current_mfi = float(mfi.iloc[-1])
        result["indicators"]["mfi_14"] = round(current_mfi, 1)
        if is_long and current_mfi > 80:
            urgency += weights["mfi"]
            result["signals"]["mfi"] = "overbought"
        elif not is_long and current_mfi < 20:
            urgency += weights["mfi"]
            result["signals"]["mfi"] = "oversold"

        # 9. OBV slope (5-period)
        obv = (volume * np.sign(close.diff())).cumsum()
        obv_slope = float(obv.iloc[-1] - obv.iloc[-6]) if len(obv) >= 6 else 0
        result["indicators"]["obv_slope_5"] = round(obv_slope, 0)
        if is_long and obv_slope < 0:
            urgency += weights["obv"]
            result["signals"]["obv"] = "declining_volume"
        elif not is_long and obv_slope > 0:
            urgency += weights["obv"]
            result["signals"]["obv"] = "rising_volume"

        # 10. Williams %R(14)
        williams_r = -100 * (highest_14 - close) / (highest_14 - lowest_14).replace(0, np.nan)
        current_wr = float(williams_r.iloc[-1])
        result["indicators"]["williams_r_14"] = round(current_wr, 1)
        if is_long and current_wr > -20:
            urgency += weights["williams_r"]
            result["signals"]["williams_r"] = "overbought"
        elif not is_long and current_wr < -80:
            urgency += weights["williams_r"]
            result["signals"]["williams_r"] = "oversold"

        # 11. Keltner Channel
        kelt_mid = close.ewm(span=20, adjust=False).mean()
        kelt_upper = kelt_mid + 2 * atr_14
        kelt_lower = kelt_mid - 2 * atr_14
        result["indicators"]["keltner_upper"] = round(float(kelt_upper.iloc[-1]), 2)
        result["indicators"]["keltner_lower"] = round(float(kelt_lower.iloc[-1]), 2)
        if is_long and current_price >= float(kelt_upper.iloc[-1]):
            urgency += weights["keltner"]
            result["signals"]["keltner"] = "above_upper_channel"
        elif not is_long and current_price <= float(kelt_lower.iloc[-1]):
            urgency += weights["keltner"]
            result["signals"]["keltner"] = "below_lower_channel"

        # 12. Ichimoku Cloud
        tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
        kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
        senkou_a = ((tenkan + kijun) / 2).shift(26)
        senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
        cloud_top = max(float(senkou_a.iloc[-1]), float(senkou_b.iloc[-1])) if not (np.isnan(senkou_a.iloc[-1]) or np.isnan(senkou_b.iloc[-1])) else current_price
        cloud_bottom = min(float(senkou_a.iloc[-1]), float(senkou_b.iloc[-1])) if not (np.isnan(senkou_a.iloc[-1]) or np.isnan(senkou_b.iloc[-1])) else current_price
        above_cloud = current_price > cloud_top
        below_cloud = current_price < cloud_bottom
        result["indicators"]["ichimoku_above_cloud"] = above_cloud
        if is_long and below_cloud:
            urgency += weights["ichimoku"]
            result["signals"]["ichimoku"] = "below_cloud"
        elif not is_long and above_cloud:
            urgency += weights["ichimoku"]
            result["signals"]["ichimoku"] = "above_cloud"

        # 13. VWAP distance
        if volume.sum() > 0:
            vwap = float((close * volume).sum() / volume.sum())
            vwap_dist = (current_price - vwap) / vwap if vwap > 0 else 0
            result["indicators"]["vwap"] = round(vwap, 2)
            result["indicators"]["vwap_distance_pct"] = round(vwap_dist * 100, 2)
            if is_long and vwap_dist > 0.02:
                urgency += weights["vwap"]
                result["signals"]["vwap"] = "extended_above_vwap"
            elif not is_long and vwap_dist < -0.02:
                urgency += weights["vwap"]
                result["signals"]["vwap"] = "extended_below_vwap"

        # 14. Volume Z-score(20)
        vol_mean = volume.rolling(20).mean()
        vol_std = volume.rolling(20).std()
        vol_z = float((volume.iloc[-1] - vol_mean.iloc[-1]) / vol_std.iloc[-1]) if vol_std.iloc[-1] > 0 else 0
        result["indicators"]["volume_zscore_20"] = round(vol_z, 2)
        if abs(vol_z) > 2:
            urgency += weights["volume_zscore"]
            result["signals"]["volume"] = f"unusual_volume_z={vol_z:.1f}"

        # 15. ATR trailing stop
        current_atr = float(atr_14.iloc[-1]) if not np.isnan(atr_14.iloc[-1]) else 0
        result["indicators"]["atr_14"] = round(current_atr, 4)
        if current_atr > 0:
            if is_long:
                atr_stop = current_price - 2 * current_atr
                result["indicators"]["atr_trailing_stop"] = round(atr_stop, 2)
            else:
                atr_stop = current_price + 2 * current_atr
                result["indicators"]["atr_trailing_stop"] = round(atr_stop, 2)

        # === Context Signals ===

        # 16. SPY 5m return (market direction)
        try:
            spy = yf.download("SPY", period="1d", interval="5m", progress=False)
            if not spy.empty and len(spy) >= 2:
                if hasattr(spy.columns, "levels"):
                    spy.columns = spy.columns.get_level_values(0)
                spy_ret = float((spy["Close"].iloc[-1] / spy["Close"].iloc[-2] - 1) * 100)
                result["indicators"]["spy_5m_return"] = round(spy_ret, 3)
                if is_long and spy_ret < -0.3:
                    urgency += weights["spy_context"]
                    result["signals"]["spy"] = f"market_selling_{spy_ret:.2f}%"
                elif not is_long and spy_ret > 0.3:
                    urgency += weights["spy_context"]
                    result["signals"]["spy"] = f"market_rallying_{spy_ret:.2f}%"
        except Exception:
            pass

        # 17. VIX level
        try:
            vix = yf.download("^VIX", period="2d", interval="1d", progress=False)
            if not vix.empty:
                if hasattr(vix.columns, "levels"):
                    vix.columns = vix.columns.get_level_values(0)
                vix_level = float(vix["Close"].iloc[-1])
                result["indicators"]["vix_level"] = round(vix_level, 1)
                if is_long and vix_level > 25:
                    urgency += weights["vix_context"]
                    result["signals"]["vix"] = f"elevated_fear_vix={vix_level:.1f}"
                if len(vix) >= 2:
                    vix_change = float((vix["Close"].iloc[-1] / vix["Close"].iloc[-2] - 1) * 100)
                    result["indicators"]["vix_change_pct"] = round(vix_change, 1)
                    if is_long and vix_change > 15:
                        urgency += int(weights["vix_context"] * 0.5)
                        result["signals"]["vix_spike"] = f"vix_spiked_{vix_change:.1f}%"
        except Exception:
            pass

        result["exit_urgency"] = min(urgency, 100)

    except Exception as e:
        result["error"] = str(e)[:200]

    return result


def main():
    parser = argparse.ArgumentParser(description="Position TA check (15+ indicators)")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--side", required=True, choices=["buy", "sell"])
    parser.add_argument("--config", default=None, help="Optional config.json for weight overrides")
    parser.add_argument("--output", default="ta.json")
    args = parser.parse_args()

    config = None
    if args.config:
        try:
            config = json.loads(Path(args.config).read_text())
        except Exception:
            pass

    result = compute_ta(args.ticker, args.side, config)
    Path(args.output).write_text(json.dumps(result, indent=2, default=str))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
