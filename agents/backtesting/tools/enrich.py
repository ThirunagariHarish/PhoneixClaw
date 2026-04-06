"""Market enrichment pipeline: add ~200 attributes to each trade row.

Usage:
    python tools/enrich.py --input output/transformed.parquet --output output/enriched.parquet
"""

import argparse
import warnings
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Helpers ─────────────────────────────────────────────────────────────────


def _safe_download(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download OHLCV data via yfinance with error handling."""
    try:
        import yfinance as yf
        data = yf.download(ticker, start=start, end=end, progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        if data.empty:
            print(f"  [yfinance] Empty result for {ticker} ({start} → {end})")
        return data
    except Exception as e:
        print(f"  [yfinance] FAILED {ticker} ({start} → {end}): {e}")
        return pd.DataFrame()


def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _calc_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _calc_sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def _calc_macd(close: pd.Series):
    ema12 = _calc_ema(close, 12)
    ema26 = _calc_ema(close, 26)
    macd_line = ema12 - ema26
    signal = _calc_ema(macd_line, 9)
    hist = macd_line - signal
    return macd_line, signal, hist


def _calc_bollinger(close: pd.Series, window: int = 20, std_dev: int = 2):
    mid = _calc_sma(close, window)
    std = close.rolling(window).std()
    upper = mid + std_dev * std
    lower = mid - std_dev * std
    return upper, mid, lower


def _calc_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _calc_stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period=14, d_period=3):
    lowest = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    k = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


def _calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    atr = _calc_atr(high, low, close, period)
    plus_di = 100 * _calc_ema(plus_dm, period) / atr.replace(0, np.nan)
    minus_di = 100 * _calc_ema(minus_dm, period) / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _calc_ema(dx, period)


# ── Main enrichment ─────────────────────────────────────────────────────────


def enrich_trade(row: pd.Series, cache: dict) -> dict:
    """Enrich a single trade row with ~200 market attributes."""
    ticker = row["ticker"]
    entry_time = pd.Timestamp(row["entry_time"])
    entry_date = entry_time.date() if hasattr(entry_time, "date") else entry_time

    # Get historical data (cached per ticker)
    cache_key = f"daily_{ticker}"

    if cache_key not in cache:
        global_start = cache.get("_global_start", str(entry_date - timedelta(days=400)))
        global_end = cache.get("_global_end", str(entry_date))
        cache[cache_key] = _safe_download(ticker, global_start, global_end)

    hist = cache[cache_key]
    if hist.empty or len(hist) < 30:
        print(f"  [enrich] Skip {ticker}: insufficient daily bars ({len(hist) if not hist.empty else 0} < 30)")
        return {}

    # Trim to data available before entry (no look-ahead)
    hist = hist[hist.index.date <= entry_date]
    if hist.empty or len(hist) < 20:
        print(f"  [enrich] Skip {ticker}: insufficient pre-entry bars ({len(hist) if not hist.empty else 0} < 20)")
        return {}

    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]
    opn = hist["Open"]

    attrs = {}

    # ── Category 1: Price Action ────────────────────────────────────────
    for d in [1, 3, 5, 10, 20]:
        attrs[f"close_{d}d"] = close.iloc[-min(d+1, len(close))] if len(close) > d else np.nan
        attrs[f"return_{d}d"] = (close.iloc[-1] - close.iloc[-min(d+1, len(close))]) / close.iloc[-min(d+1, len(close))] if len(close) > d else np.nan

    if len(close) >= 2:
        attrs["gap_pct"] = (opn.iloc[-1] - close.iloc[-2]) / close.iloc[-2]
        attrs["range_pct"] = (high.iloc[-1] - low.iloc[-1]) / close.iloc[-1]
        attrs["body_pct"] = abs(close.iloc[-1] - opn.iloc[-1]) / close.iloc[-1]

    atr = _calc_atr(high, low, close)
    attrs["atr_14"] = atr.iloc[-1] if not atr.empty else np.nan
    attrs["atr_pct"] = attrs["atr_14"] / close.iloc[-1] if close.iloc[-1] != 0 else np.nan

    for d in [5, 20]:
        attrs[f"high_{d}d"] = high.iloc[-d:].max() if len(high) >= d else np.nan
        attrs[f"low_{d}d"] = low.iloc[-d:].min() if len(low) >= d else np.nan

    if len(close) >= 252:
        h52 = high.iloc[-252:].max()
        l52 = low.iloc[-252:].min()
        attrs["dist_from_52w_high"] = (close.iloc[-1] - h52) / h52
        attrs["dist_from_52w_low"] = (close.iloc[-1] - l52) / l52

    greens = 0
    for i in range(2, min(11, len(close)+1)):
        if close.iloc[-i] < close.iloc[-i+1]:
            greens += 1
        else:
            break
    attrs["consecutive_green"] = greens

    # Fibonacci retracement levels relative to 20d range
    if len(high) >= 20:
        h20 = high.iloc[-20:].max()
        l20 = low.iloc[-20:].min()
        rng = h20 - l20
        if rng > 0:
            for fib_level in [0.236, 0.382, 0.5, 0.618, 0.786]:
                fib_price = h20 - fib_level * rng
                attrs[f"fib_{str(fib_level).replace('.', '')}"] = fib_price
                attrs[f"dist_fib_{str(fib_level).replace('.', '')}"] = (close.iloc[-1] - fib_price) / close.iloc[-1]

    # Higher highs / lower lows count
    for lookback in [5, 10]:
        if len(high) > lookback:
            hh = sum(1 for j in range(1, lookback) if high.iloc[-j] > high.iloc[-j - 1])
            ll = sum(1 for j in range(1, lookback) if low.iloc[-j] < low.iloc[-j - 1])
            attrs[f"higher_highs_{lookback}d"] = hh
            attrs[f"lower_lows_{lookback}d"] = ll

    # Inside bar detection (today's range within yesterday's range)
    if len(high) >= 2:
        attrs["inside_bar"] = float(high.iloc[-1] <= high.iloc[-2] and low.iloc[-1] >= low.iloc[-2])

    # Candle patterns
    if len(close) >= 2:
        body = abs(close.iloc[-1] - opn.iloc[-1])
        full_range = high.iloc[-1] - low.iloc[-1]
        if full_range > 0:
            body_ratio = body / full_range
            upper_wick = high.iloc[-1] - max(close.iloc[-1], opn.iloc[-1])
            lower_wick = min(close.iloc[-1], opn.iloc[-1]) - low.iloc[-1]
            attrs["is_doji"] = float(body_ratio < 0.1)
            attrs["is_hammer"] = float(lower_wick > 2 * body and upper_wick < body * 0.5)
            prev_body = close.iloc[-2] - opn.iloc[-2]
            curr_body = close.iloc[-1] - opn.iloc[-1]
            attrs["is_engulfing_bull"] = float(
                prev_body < 0 and curr_body > 0 and
                opn.iloc[-1] <= close.iloc[-2] and close.iloc[-1] >= opn.iloc[-2]
            )
            attrs["is_engulfing_bear"] = float(
                prev_body > 0 and curr_body < 0 and
                opn.iloc[-1] >= close.iloc[-2] and close.iloc[-1] <= opn.iloc[-2]
            )

    # ── Category 2: Technical Indicators ────────────────────────────────
    for p in [7, 14, 21]:
        rsi = _calc_rsi(close, p)
        attrs[f"rsi_{p}"] = rsi.iloc[-1] if not rsi.empty else np.nan

    macd_line, macd_signal, macd_hist = _calc_macd(close)
    attrs["macd_line"] = macd_line.iloc[-1] if not macd_line.empty else np.nan
    attrs["macd_signal"] = macd_signal.iloc[-1] if not macd_signal.empty else np.nan
    attrs["macd_histogram"] = macd_hist.iloc[-1] if not macd_hist.empty else np.nan
    attrs["macd_cross_up"] = float(macd_line.iloc[-1] > macd_signal.iloc[-1] and macd_line.iloc[-2] <= macd_signal.iloc[-2]) if len(macd_line) >= 2 else 0.0

    bb_upper, bb_mid, bb_lower = _calc_bollinger(close)
    attrs["bb_upper"] = bb_upper.iloc[-1] if not bb_upper.empty else np.nan
    attrs["bb_middle"] = bb_mid.iloc[-1] if not bb_mid.empty else np.nan
    attrs["bb_lower"] = bb_lower.iloc[-1] if not bb_lower.empty else np.nan
    if not np.isnan(attrs.get("bb_upper", np.nan)) and (attrs["bb_upper"] - attrs["bb_lower"]) != 0:
        attrs["bb_position"] = (close.iloc[-1] - attrs["bb_lower"]) / (attrs["bb_upper"] - attrs["bb_lower"])
        attrs["bb_width"] = (attrs["bb_upper"] - attrs["bb_lower"]) / attrs["bb_middle"] if attrs["bb_middle"] != 0 else np.nan

    stoch_k, stoch_d = _calc_stochastic(high, low, close)
    attrs["stoch_k"] = stoch_k.iloc[-1] if not stoch_k.empty else np.nan
    attrs["stoch_d"] = stoch_d.iloc[-1] if not stoch_d.empty else np.nan
    attrs["adx_14"] = _calc_adx(high, low, close).iloc[-1]

    cci_period = 20
    if len(close) >= cci_period:
        tp = (high + low + close) / 3
        sma_tp = tp.rolling(cci_period).mean()
        mad = tp.rolling(cci_period).apply(lambda x: np.abs(x - x.mean()).mean())
        attrs["cci_20"] = ((tp.iloc[-1] - sma_tp.iloc[-1]) / (0.015 * mad.iloc[-1])) if mad.iloc[-1] != 0 else np.nan

    obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    attrs["obv"] = obv.iloc[-1]
    attrs["obv_slope_5"] = (obv.iloc[-1] - obv.iloc[-min(6, len(obv))]) / 5 if len(obv) >= 5 else np.nan

    # Williams %R
    if len(close) >= 14:
        highest14 = high.rolling(14).max()
        lowest14 = low.rolling(14).min()
        wr = -100 * (highest14.iloc[-1] - close.iloc[-1]) / (highest14.iloc[-1] - lowest14.iloc[-1]) if (highest14.iloc[-1] - lowest14.iloc[-1]) > 0 else np.nan
        attrs["williams_r_14"] = wr

    # Rate of Change
    for roc_d in [5, 10]:
        if len(close) > roc_d:
            attrs[f"roc_{roc_d}d"] = (close.iloc[-1] - close.iloc[-roc_d - 1]) / close.iloc[-roc_d - 1]

    # Money Flow Index (14)
    if len(close) >= 15:
        tp = (high + low + close) / 3
        mf = tp * volume
        pos_mf = mf.where(tp.diff() > 0, 0.0).rolling(14).sum()
        neg_mf = mf.where(tp.diff() <= 0, 0.0).rolling(14).sum()
        mfi = 100 - (100 / (1 + pos_mf / neg_mf.replace(0, np.nan)))
        attrs["mfi_14"] = mfi.iloc[-1] if not mfi.empty else np.nan

    # TRIX (15-period)
    if len(close) >= 45:
        ema1 = _calc_ema(close, 15)
        ema2 = _calc_ema(ema1, 15)
        ema3 = _calc_ema(ema2, 15)
        attrs["trix_15"] = ((ema3.iloc[-1] - ema3.iloc[-2]) / ema3.iloc[-2]) * 100 if ema3.iloc[-2] != 0 else np.nan

    # Keltner Channel
    if len(close) >= 20:
        kc_mid = _calc_ema(close, 20)
        kc_atr = _calc_atr(high, low, close, 10)
        kc_upper = kc_mid + 2 * kc_atr
        kc_lower = kc_mid - 2 * kc_atr
        attrs["keltner_upper"] = kc_upper.iloc[-1] if not kc_upper.empty else np.nan
        attrs["keltner_lower"] = kc_lower.iloc[-1] if not kc_lower.empty else np.nan
        kc_range = kc_upper.iloc[-1] - kc_lower.iloc[-1]
        attrs["keltner_position"] = (close.iloc[-1] - kc_lower.iloc[-1]) / kc_range if kc_range > 0 else np.nan

    # Donchian Channel (20d)
    if len(high) >= 20:
        dc_upper = high.rolling(20).max().iloc[-1]
        dc_lower = low.rolling(20).min().iloc[-1]
        attrs["donchian_upper"] = dc_upper
        attrs["donchian_lower"] = dc_lower
        dc_range = dc_upper - dc_lower
        attrs["donchian_position"] = (close.iloc[-1] - dc_lower) / dc_range if dc_range > 0 else np.nan

    # Ichimoku (simplified)
    if len(close) >= 52:
        tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
        kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
        senkou_a = ((tenkan + kijun) / 2).shift(26)
        senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
        attrs["ichimoku_tenkan"] = tenkan.iloc[-1] if not tenkan.empty else np.nan
        attrs["ichimoku_kijun"] = kijun.iloc[-1] if not kijun.empty else np.nan
        attrs["ichimoku_above_cloud"] = float(
            close.iloc[-1] > max(senkou_a.iloc[-1], senkou_b.iloc[-1])
        ) if not (np.isnan(senkou_a.iloc[-1]) or np.isnan(senkou_b.iloc[-1])) else np.nan

    # Parabolic SAR direction (simplified via trend)
    if len(close) >= 5:
        sar_bullish = float(close.iloc[-1] > close.iloc[-3])
        attrs["parabolic_sar_bullish"] = sar_bullish

    # Chaikin Money Flow (20)
    if len(close) >= 20:
        clv = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
        cmf = (clv * volume).rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)
        attrs["cmf_20"] = cmf.iloc[-1] if not cmf.empty else np.nan

    # Stochastic RSI
    if len(close) >= 28:
        rsi_vals = _calc_rsi(close, 14)
        rsi_low = rsi_vals.rolling(14).min()
        rsi_high = rsi_vals.rolling(14).max()
        stoch_rsi = (rsi_vals - rsi_low) / (rsi_high - rsi_low).replace(0, np.nan)
        srsi_k = stoch_rsi.rolling(3).mean() * 100
        srsi_d = srsi_k.rolling(3).mean()
        attrs["stoch_rsi_k"] = srsi_k.iloc[-1] if not srsi_k.empty else np.nan
        attrs["stoch_rsi_d"] = srsi_d.iloc[-1] if not srsi_d.empty else np.nan

    # ── Category 3: Moving Averages ─────────────────────────────────────
    for w in [5, 10, 20, 50, 100, 200]:
        sma = _calc_sma(close, w)
        ema = _calc_ema(close, w)
        attrs[f"sma_{w}"] = sma.iloc[-1] if len(close) >= w else np.nan
        attrs[f"ema_{w}"] = ema.iloc[-1] if len(close) >= w else np.nan

    for w in [20, 50, 200]:
        sma_val = attrs.get(f"sma_{w}", np.nan)
        if not np.isnan(sma_val) and sma_val != 0:
            attrs[f"dist_sma_{w}"] = (close.iloc[-1] - sma_val) / sma_val

    sma20 = attrs.get("sma_20", np.nan)
    sma50 = attrs.get("sma_50", np.nan)
    sma200 = attrs.get("sma_200", np.nan)
    attrs["sma_20_50_cross"] = float(sma20 > sma50) if not (np.isnan(sma20) or np.isnan(sma50)) else np.nan
    attrs["sma_50_200_cross"] = float(sma50 > sma200) if not (np.isnan(sma50) or np.isnan(sma200)) else np.nan
    attrs["above_all_sma"] = float(close.iloc[-1] > sma20 and close.iloc[-1] > sma50 and close.iloc[-1] > sma200) if not any(np.isnan(x) for x in [sma20, sma50, sma200]) else np.nan

    # ── Category 3b: Volatility ──────────────────────────────────────────
    log_returns = np.log(close / close.shift(1)).dropna()
    for vol_w in [5, 10, 20, 60]:
        if len(log_returns) >= vol_w:
            attrs[f"realized_vol_{vol_w}d"] = float(log_returns.iloc[-vol_w:].std() * np.sqrt(252))

    if attrs.get("realized_vol_5d") and attrs.get("realized_vol_20d") and attrs["realized_vol_20d"] > 0:
        attrs["vol_ratio_5_20"] = attrs["realized_vol_5d"] / attrs["realized_vol_20d"]

    # Parkinson volatility (20d)
    if len(high) >= 20:
        hl_ratio = np.log(high.iloc[-20:] / low.iloc[-20:])
        attrs["parkinson_vol"] = float(np.sqrt((1 / (4 * 20 * np.log(2))) * (hl_ratio ** 2).sum()) * np.sqrt(252))

    # Garman-Klass volatility (20d)
    if len(close) >= 21:
        gc_close = close.iloc[-21:]
        gc_high = high.iloc[-21:]
        gc_low = low.iloc[-21:]
        gc_open = opn.iloc[-21:]
        n = len(gc_close) - 1
        hl = np.log(gc_high.iloc[1:].values / gc_low.iloc[1:].values) ** 2
        co = np.log(gc_close.iloc[1:].values / gc_open.iloc[1:].values) ** 2
        attrs["garman_klass_vol"] = float(np.sqrt((0.5 * hl - (2 * np.log(2) - 1) * co).mean()) * np.sqrt(252))

    # ATR percentile (30d)
    if len(atr) >= 30 and not atr.empty:
        atr_30 = atr.iloc[-30:]
        attrs["atr_percentile_30d"] = float((atr_30 < atr.iloc[-1]).mean())

    # ── Category 4: Volume ──────────────────────────────────────────────
    attrs["volume"] = volume.iloc[-1]
    for vol_w in [5, 10, 20]:
        vol_sma = _calc_sma(volume, vol_w)
        attrs[f"volume_sma_{vol_w}"] = vol_sma.iloc[-1] if not vol_sma.empty else np.nan
        if not vol_sma.empty and vol_sma.iloc[-1] > 0:
            attrs[f"volume_ratio_{vol_w}"] = volume.iloc[-1] / vol_sma.iloc[-1]

    attrs["volume_breakout"] = float(attrs.get("volume_ratio_20", 0) > 2.0)

    # Volume Z-score (20d)
    if len(volume) >= 20:
        vol_std = volume.iloc[-20:].std()
        vol_mean = volume.iloc[-20:].mean()
        attrs["volume_zscore_20"] = float((volume.iloc[-1] - vol_mean) / vol_std) if vol_std > 0 else 0.0

    # Up-volume ratio (5d) — fraction of days where close > open
    if len(close) >= 5:
        up_days = sum(1 for j in range(1, 6) if close.iloc[-j] > opn.iloc[-j])
        attrs["up_volume_ratio_5d"] = up_days / 5.0

    # VWAP distance (using daily data)
    if not volume.empty and volume.sum() > 0:
        vwap = (close * volume).cumsum() / volume.cumsum().replace(0, np.nan)
        attrs["vwap_distance"] = (close.iloc[-1] - vwap.iloc[-1]) / close.iloc[-1] if not np.isnan(vwap.iloc[-1]) else np.nan

    # Accumulation/Distribution line
    if len(close) >= 2:
        clv = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
        ad_line = (clv.fillna(0) * volume).cumsum()
        attrs["ad_line"] = ad_line.iloc[-1] if not ad_line.empty else np.nan

    # Force Index (13-period EMA)
    if len(close) >= 14:
        force = close.diff() * volume
        force_ema = _calc_ema(force.fillna(0), 13)
        attrs["force_index_13"] = force_ema.iloc[-1] if not force_ema.empty else np.nan

    # ── Category 5: Market Context ──────────────────────────────────────
    for ctx_ticker, prefix in [("SPY", "spy"), ("QQQ", "qqq"), ("IWM", "iwm"), ("DIA", "dia")]:
        ctx_key = f"daily_{ctx_ticker}"
        if ctx_key not in cache:
            cache[ctx_key] = _safe_download(ctx_ticker, cache.get("_global_start", ""), cache.get("_global_end", ""))
        ctx = cache[ctx_key]
        if not ctx.empty and len(ctx) >= 2:
            ctx = ctx[ctx.index.date <= entry_date]
            if len(ctx) >= 2:
                attrs[f"{prefix}_return_1d"] = (ctx["Close"].iloc[-1] - ctx["Close"].iloc[-2]) / ctx["Close"].iloc[-2]
                if len(ctx) >= 6:
                    attrs[f"{prefix}_return_5d"] = (ctx["Close"].iloc[-1] - ctx["Close"].iloc[-6]) / ctx["Close"].iloc[-6]

    # Sector ETFs
    sector_etfs = {
        "XLF": "financials", "XLK": "technology", "XLE": "energy",
        "XLV": "healthcare", "XLI": "industrials", "XLC": "communication",
        "XLU": "utilities", "XLP": "consumer_staples", "XLB": "materials", "XLRE": "real_estate",
    }
    for sect_ticker, sect_name in sector_etfs.items():
        sect_key = f"daily_{sect_ticker}"
        if sect_key not in cache:
            cache[sect_key] = _safe_download(sect_ticker, cache.get("_global_start", ""), cache.get("_global_end", ""))
        sect = cache[sect_key]
        if not sect.empty and len(sect) >= 2:
            sect = sect[sect.index.date <= entry_date]
            if len(sect) >= 2:
                attrs[f"sector_{sect_name}_1d"] = (sect["Close"].iloc[-1] - sect["Close"].iloc[-2]) / sect["Close"].iloc[-2]

    # Fixed income / gold proxies
    for proxy_ticker, proxy_prefix in [("TLT", "tlt"), ("GLD", "gld")]:
        p_key = f"daily_{proxy_ticker}"
        if p_key not in cache:
            cache[p_key] = _safe_download(proxy_ticker, cache.get("_global_start", ""), cache.get("_global_end", ""))
        p_data = cache[p_key]
        if not p_data.empty and len(p_data) >= 2:
            p_data = p_data[p_data.index.date <= entry_date]
            if len(p_data) >= 2:
                attrs[f"{proxy_prefix}_return_1d"] = (p_data["Close"].iloc[-1] - p_data["Close"].iloc[-2]) / p_data["Close"].iloc[-2]

    vix_key = "daily_^VIX"
    if vix_key not in cache:
        cache[vix_key] = _safe_download("^VIX", cache.get("_global_start", ""), cache.get("_global_end", ""))
    vix = cache[vix_key]
    if not vix.empty:
        vix = vix[vix.index.date <= entry_date]
        if len(vix) >= 2:
            attrs["vix_level"] = vix["Close"].iloc[-1]
            attrs["vix_change_1d"] = vix["Close"].iloc[-1] - vix["Close"].iloc[-2]
            if len(vix) >= 6:
                attrs["vix_change_5d"] = vix["Close"].iloc[-1] - vix["Close"].iloc[-6]
            if len(vix) >= 30:
                attrs["vix_percentile_30d"] = (vix["Close"].iloc[-30:] < vix["Close"].iloc[-1]).mean()
            attrs["vix_above_20"] = float(vix["Close"].iloc[-1] > 20)
            attrs["vix_above_30"] = float(vix["Close"].iloc[-1] > 30)

    # Correlation with SPY
    spy_key = "daily_SPY"
    if spy_key in cache and not cache[spy_key].empty and len(close) >= 20:
        spy_close = cache[spy_key]
        spy_close = spy_close[spy_close.index.date <= entry_date]["Close"]
        if len(spy_close) >= 20:
            common_idx = close.index.intersection(spy_close.index)[-20:]
            if len(common_idx) >= 10:
                attrs["corr_spy_20d"] = close.loc[common_idx].pct_change().corr(spy_close.loc[common_idx].pct_change())

    # ── Category 6: Time Features ───────────────────────────────────────
    if hasattr(entry_time, "hour"):
        attrs["hour_of_day"] = entry_time.hour
        attrs["minute_of_hour"] = entry_time.minute
        attrs["is_pre_market"] = float(entry_time.hour < 9 or (entry_time.hour == 9 and entry_time.minute < 30))
        attrs["is_first_hour"] = float(entry_time.hour == 9 or (entry_time.hour == 10 and entry_time.minute <= 30))
        attrs["is_last_hour"] = float(entry_time.hour == 15)
        attrs["is_power_hour"] = float(entry_time.hour == 15 and entry_time.minute >= 0)

    if hasattr(entry_date, "weekday"):
        attrs["day_of_week"] = entry_date.weekday() if hasattr(entry_date, "weekday") else entry_time.weekday()
        attrs["is_monday"] = float(attrs["day_of_week"] == 0)
        attrs["is_friday"] = float(attrs["day_of_week"] == 4)
        attrs["month"] = entry_date.month if hasattr(entry_date, "month") else entry_time.month
        attrs["quarter"] = (attrs["month"] - 1) // 3 + 1
        attrs["day_of_month"] = entry_date.day if hasattr(entry_date, "day") else entry_time.day

    # OPEX
    import calendar
    yr = entry_date.year if hasattr(entry_date, "year") else entry_time.year
    mo = entry_date.month if hasattr(entry_date, "month") else entry_time.month
    c = calendar.Calendar()
    fridays = [d for d in c.itermonthdays2(yr, mo) if d[0] != 0 and d[1] == 4]
    opex_day = fridays[2][0] if len(fridays) >= 3 else 20
    from datetime import date
    opex_date = date(yr, mo, opex_day)
    attrs["days_to_opex"] = (opex_date - entry_date).days if hasattr(entry_date, "year") else 0
    attrs["is_opex_week"] = float(abs(attrs["days_to_opex"]) <= 5)

    # ── Category 7: Sentiment & Events ────────────────────────────────
    # FinBERT sentiment on the original Discord message (reuse model from cache)
    msg_text = row.get("raw_message", row.get("content", ""))
    if msg_text and isinstance(msg_text, str):
        try:
            if "_sentiment_clf" not in cache:
                from shared.nlp.sentiment_classifier import SentimentClassifier
                cache["_sentiment_clf"] = SentimentClassifier()
            _clf = cache["_sentiment_clf"]
            sent = _clf.classify(msg_text)
            attrs["sentiment_score"] = sent.score
            attrs["sentiment_confidence"] = sent.confidence
            attrs["sentiment_numeric"] = sent.numeric
            attrs["sentiment_bullish"] = float(sent.is_bullish)
            attrs["sentiment_bearish"] = float(sent.is_bearish)
        except Exception:
            attrs["sentiment_score"] = np.nan
            attrs["sentiment_confidence"] = np.nan
            attrs["sentiment_numeric"] = np.nan
            attrs["sentiment_bullish"] = np.nan
            attrs["sentiment_bearish"] = np.nan

    # Earnings calendar (yfinance) — cached per ticker
    try:
        fund_key = f"_fundamentals_{ticker}"
        if fund_key not in cache:
            import yfinance as yf
            yf_ticker = yf.Ticker(ticker)
            cache[fund_key] = {
                "calendar": yf_ticker.calendar,
                "recommendations": yf_ticker.recommendations,
            }
        fund = cache[fund_key]
        cal = fund["calendar"]
        if cal is not None:
            earn_date = None
            if isinstance(cal, dict):
                earn_date = cal.get("Earnings Date")
                if isinstance(earn_date, list) and earn_date:
                    earn_date = earn_date[0]
            elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                earn_date = cal.loc["Earnings Date"].iloc[0]
            if earn_date:
                earn_dt = pd.Timestamp(earn_date).date()
                attrs["days_to_earnings"] = (earn_dt - entry_date).days
                attrs["earnings_within_7d"] = float(abs(attrs["days_to_earnings"]) <= 7)
                attrs["earnings_within_14d"] = float(abs(attrs["days_to_earnings"]) <= 14)
        recs = fund["recommendations"]
        if recs is not None and not recs.empty:
            if hasattr(recs.index, 'date'):
                recs = recs[recs.index.date <= entry_date]
            recent = recs.tail(5)
            grade_map = {"Strong Buy": 5, "Buy": 4, "Overweight": 4,
                         "Hold": 3, "Neutral": 3, "Equal-Weight": 3,
                         "Underweight": 2, "Sell": 1, "Strong Sell": 0}
            grades = []
            for _, r in recent.iterrows():
                g = r.get("To Grade", r.get("toGrade", ""))
                if g in grade_map:
                    grades.append(grade_map[g])
            if grades:
                attrs["analyst_avg_grade"] = np.mean(grades)
                attrs["analyst_recent_upgrades"] = sum(1 for g in grades if g >= 4)
                attrs["analyst_recent_downgrades"] = sum(1 for g in grades if g <= 2)
    except Exception:
        pass

    # FOMC/CPI/NFP proximity
    fomc_dates = [
        "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
        "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
        "2025-07-30", "2025-09-17", "2025-11-05", "2025-12-17",
        "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
    ]
    cpi_dates = [
        "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10",
        "2024-05-15", "2024-06-12", "2024-07-11", "2024-08-14",
        "2024-09-11", "2024-10-10", "2024-11-13", "2024-12-11",
        "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10",
        "2025-05-13", "2025-06-11", "2025-07-15", "2025-08-12",
        "2025-09-10", "2025-10-14", "2025-11-12", "2025-12-10",
        "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-10",
        "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
        "2026-09-11", "2026-10-13", "2026-11-10", "2026-12-10",
    ]
    from datetime import date as date_cls
    for name, dates in [("fomc", fomc_dates), ("cpi", cpi_dates)]:
        future = [d for d in (date_cls.fromisoformat(d) for d in dates) if d >= entry_date]
        if future:
            days_away = (future[0] - entry_date).days
            attrs[f"days_to_{name}"] = days_away
            attrs[f"{name}_within_3d"] = float(days_away <= 3)

    # NFP (Non-Farm Payrolls) — first Friday of each month
    nfp_dates = [
        "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05",
        "2024-05-03", "2024-06-07", "2024-07-05", "2024-08-02",
        "2024-09-06", "2024-10-04", "2024-11-01", "2024-12-06",
        "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04",
        "2025-05-02", "2025-06-06", "2025-07-03", "2025-08-01",
        "2025-09-05", "2025-10-03", "2025-11-07", "2025-12-05",
        "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
        "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07",
        "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
    ]
    nfp_future = [d for d in (date_cls.fromisoformat(d) for d in nfp_dates) if d >= entry_date]
    if nfp_future:
        nfp_away = (nfp_future[0] - entry_date).days
        attrs["days_to_nfp"] = nfp_away
        attrs["nfp_within_3d"] = float(nfp_away <= 3)

    # Quad witching (3rd Friday of Mar/Jun/Sep/Dec)
    if hasattr(entry_date, "month") and entry_date.month in (3, 6, 9, 12):
        fridays_qw = [d for d in c.itermonthdays2(yr, entry_date.month) if d[0] != 0 and d[1] == 4]
        qw_day = fridays_qw[2][0] if len(fridays_qw) >= 3 else 20
        qw_date = date_cls(yr, entry_date.month, qw_day)
        attrs["is_quad_witching_week"] = float(abs((qw_date - entry_date).days) <= 5)
    else:
        attrs["is_quad_witching_week"] = 0.0

    # ── Category 8: Options Data (cached per ticker) ──────────────────
    uw_key = f"_uw_{ticker}"
    if uw_key not in cache:
        try:
            import asyncio
            from shared.unusual_whales.client import UnusualWhalesClient
            if "_uw_client" not in cache:
                cache["_uw_client"] = UnusualWhalesClient()
                cache["_uw_loop"] = asyncio.new_event_loop()
            uw = cache["_uw_client"]
            _loop = cache["_uw_loop"]
            uw_data = {}
            uw_data["flow"] = _loop.run_until_complete(uw.get_options_flow(ticker=ticker))
            uw_data["gex"] = _loop.run_until_complete(uw.get_gex(ticker))
            try:
                uw_data["chain"] = _loop.run_until_complete(uw.get_option_chain(ticker))
            except Exception:
                uw_data["chain"] = None
            cache[uw_key] = uw_data
        except Exception:
            cache[uw_key] = None

    uw_data = cache.get(uw_key)
    if uw_data:
        flow = uw_data.get("flow")
        if flow:
            total_premium = sum(float(f.premium or 0) for f in flow[:50])
            call_premium = sum(float(f.premium or 0) for f in flow[:50]
                               if f.option_type == "CALL")
            put_premium = total_premium - call_premium
            attrs["options_total_premium_50"] = total_premium
            attrs["options_call_premium_pct"] = call_premium / total_premium if total_premium > 0 else 0.5
            attrs["options_put_call_ratio"] = put_premium / call_premium if call_premium > 0 else np.nan
            attrs["options_flow_count"] = len(flow)
        gex = uw_data.get("gex")
        if gex and gex.total_gex is not None:
            attrs["gex_value"] = float(gex.total_gex)
            attrs["gex_positive"] = float(attrs.get("gex_value", 0) > 0)
        chain = uw_data.get("chain")
        contracts = chain.contracts if chain else []
        if contracts:
            ivs = [c.implied_volatility for c in contracts if c.implied_volatility]
            if ivs:
                current_iv = ivs[0]
                iv_min, iv_max = min(ivs), max(ivs)
                attrs["iv_current"] = current_iv
                attrs["iv_rank"] = ((current_iv - iv_min) / (iv_max - iv_min)
                                    if iv_max > iv_min else 0.5)
                attrs["iv_percentile"] = sum(1 for iv in ivs if iv <= current_iv) / len(ivs)
            entry_price = float(row.get("entry_price", 0))
            atm = [c for c in contracts if entry_price > 0 and
                   abs(c.strike - entry_price) < entry_price * 0.05]
            if not atm:
                atm = contracts[:5]
            if atm:
                attrs["avg_delta"] = np.mean([c.delta or 0 for c in atm])
                attrs["avg_gamma"] = np.mean([c.gamma or 0 for c in atm])
                attrs["avg_theta"] = np.mean([c.theta or 0 for c in atm])
                attrs["avg_vega"] = np.mean([c.vega or 0 for c in atm])

    # ── Category 9: Intraday Features (5m bars, cached per ticker) ────
    intra_key = f"_intra5m_{ticker}"
    if intra_key not in cache:
        try:
            import yfinance as yf_intra
            intra_start = cache.get("_global_start_5m", str(entry_date - timedelta(days=5)))
            intra_end = cache.get("_global_end", str(entry_date))
            intra_hist = yf_intra.download(ticker, start=intra_start, end=intra_end, interval="5m", progress=False)
            if isinstance(intra_hist.columns, pd.MultiIndex):
                intra_hist.columns = intra_hist.columns.get_level_values(0)
            cache[intra_key] = intra_hist
        except Exception:
            cache[intra_key] = pd.DataFrame()

    intra_hist = cache[intra_key]
    if not intra_hist.empty:
        intra_slice = intra_hist[intra_hist.index.date <= entry_date]
        if len(intra_slice) >= 20:
            ic = intra_slice["Close"]
            iv = intra_slice["Volume"]
            intra_rsi = _calc_rsi(ic, 14)
            attrs["intraday_rsi_14"] = intra_rsi.iloc[-1] if not intra_rsi.empty else np.nan
            i_macd, i_sig, i_hist = _calc_macd(ic)
            attrs["intraday_macd_hist"] = i_hist.iloc[-1] if not i_hist.empty else np.nan
            if iv.sum() > 0:
                intra_vwap = float((ic * iv).sum() / iv.sum())
                attrs["intraday_vwap"] = intra_vwap
                attrs["price_vs_intraday_vwap"] = (ic.iloc[-1] - intra_vwap) / intra_vwap if intra_vwap > 0 else np.nan
            if len(iv) >= 20:
                attrs["intraday_vol_ratio"] = float(iv.iloc[-1] / iv.iloc[-20:].mean()) if iv.iloc[-20:].mean() > 0 else np.nan

    return attrs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    df = pd.read_parquet(args.input)
    print(f"Enriching {len(df)} trades...")

    # ── Pre-download: fetch each ticker exactly once with the widest date range ──
    import time
    t0 = time.time()

    all_dates = pd.to_datetime(df["entry_time"]).dt.date
    global_min_date = all_dates.min() - timedelta(days=400)
    global_max_date = all_dates.max() + timedelta(days=1)
    global_start = str(global_min_date)
    global_end = str(global_max_date)

    trade_tickers = sorted(df["ticker"].dropna().unique().tolist())
    context_tickers = (
        ["SPY", "QQQ", "IWM", "DIA", "^VIX", "TLT", "GLD"]
        + ["XLF", "XLK", "XLE", "XLV", "XLI", "XLC", "XLU", "XLP", "XLB", "XLRE"]
    )
    all_tickers = sorted(set(trade_tickers + context_tickers))

    cache = {
        "_global_start": global_start,
        "_global_end": global_end,
        "_global_start_5m": str(all_dates.min() - timedelta(days=5)),
    }

    print(f"  Pre-downloading daily data for {len(all_tickers)} tickers ({global_start} → {global_end}) ...")
    for i, tk in enumerate(all_tickers):
        cache[f"daily_{tk}"] = _safe_download(tk, global_start, global_end)
        if (i + 1) % 10 == 0:
            print(f"    Downloaded {i + 1}/{len(all_tickers)} tickers")

    print(f"  Pre-downloading 5m intraday data for {len(trade_tickers)} trade tickers ...")
    for i, tk in enumerate(trade_tickers):
        try:
            import yfinance as yf_intra
            intra = yf_intra.download(tk, start=cache["_global_start_5m"], end=global_end, interval="5m", progress=False)
            if isinstance(intra.columns, pd.MultiIndex):
                intra.columns = intra.columns.get_level_values(0)
            cache[f"_intra5m_{tk}"] = intra
        except Exception:
            cache[f"_intra5m_{tk}"] = pd.DataFrame()
        if (i + 1) % 10 == 0:
            print(f"    Downloaded {i + 1}/{len(trade_tickers)} intraday tickers")

    print(f"  Pre-download done in {time.time() - t0:.1f}s ({len(cache)} cache entries)")

    enriched_rows = []
    n_success = 0
    n_empty = 0

    for idx, row in df.iterrows():
        attrs = enrich_trade(row, cache)
        enriched_rows.append(attrs)
        if attrs:
            n_success += 1
        else:
            n_empty += 1

        if (idx + 1) % 50 == 0:
            print(f"  Enriched {idx + 1}/{len(df)} trades (success={n_success}, skipped={n_empty})...")

    # Cleanup UW client
    if "_uw_client" in cache and "_uw_loop" in cache:
        try:
            cache["_uw_loop"].run_until_complete(cache["_uw_client"].close())
            cache["_uw_loop"].close()
        except Exception:
            pass

    enriched_df = pd.DataFrame(enriched_rows)
    result = pd.concat([df.reset_index(drop=True), enriched_df], axis=1)

    n_new_cols = len(enriched_df.columns)
    print(f"Added {n_new_cols} market attributes ({n_success}/{len(df)} trades enriched, {n_empty} skipped)")
    if n_empty > 0 and n_success == 0:
        print("WARNING: ALL trades returned empty enrichment! Check yfinance connectivity and ticker validity.")

    # --- Rolling analyst features ---
    if "analyst" in result.columns:
        result = result.sort_values("entry_time").reset_index(drop=True)
        for window in [10, 20]:
            grp = result.groupby("analyst")["is_profitable"]
            result[f"analyst_win_rate_{window}"] = grp.transform(
                lambda s: s.shift(1).rolling(window, min_periods=1).mean()
            )
        grp_pnl = result.groupby("analyst")["pnl_pct"] if "pnl_pct" in result.columns else None
        if grp_pnl is not None:
            result["analyst_avg_pnl_10"] = grp_pnl.transform(
                lambda s: s.shift(1).rolling(10, min_periods=1).mean()
            )

        def _streak(s):
            shifted = s.shift(1).fillna(0)
            streaks = []
            current = 0
            for v in shifted:
                current = current + 1 if v == 1 else 0
                streaks.append(current)
            return pd.Series(streaks, index=s.index)

        result["analyst_win_streak"] = result.groupby("analyst")["is_profitable"].transform(_streak)
        print("Added rolling analyst features")

    # --- Category 10: Temporal Cross-Trade Features ---
    result = result.sort_values("entry_time").reset_index(drop=True)

    if "ticker" in result.columns and "is_profitable" in result.columns:
        for window in [5, 10]:
            grp_ticker = result.groupby("ticker")["is_profitable"]
            result[f"ticker_win_rate_{window}"] = grp_ticker.transform(
                lambda s: s.shift(1).rolling(window, min_periods=1).mean()
            )
        if "pnl_pct" in result.columns:
            result["ticker_avg_pnl_5"] = result.groupby("ticker")["pnl_pct"].transform(
                lambda s: s.shift(1).rolling(5, min_periods=1).mean()
            )
        result["ticker_trade_count"] = result.groupby("ticker").cumcount()

        def _ticker_streak(s):
            shifted = s.shift(1).fillna(0)
            streaks = []
            current = 0
            for v in shifted:
                current = current + 1 if v == 1 else 0
                streaks.append(current)
            return pd.Series(streaks, index=s.index)

        result["streak_same_ticker"] = result.groupby("ticker")["is_profitable"].transform(_ticker_streak)

        if "entry_time" in result.columns:
            result["days_since_last_trade"] = result.groupby("ticker")["entry_time"].transform(
                lambda s: s.diff().dt.total_seconds() / 86400
            ).fillna(0)
            wins = result[result["is_profitable"] == True]
            if len(wins) > 0:
                result["days_since_last_win"] = result.groupby("ticker")["entry_time"].transform(
                    lambda s: s.diff().dt.total_seconds() / 86400
                ).fillna(0)

    if "return_1d" in result.columns and "return_5d" in result.columns:
        r1 = result.get("return_1d", 0)
        r5 = result.get("return_5d", 0)
        r10 = result.get("return_10d", 0) if "return_10d" in result.columns else 0
        r20 = result.get("return_20d", 0) if "return_20d" in result.columns else 0
        result["momentum_composite"] = 0.4 * r1 + 0.3 * r5 + 0.2 * r10 + 0.1 * r20
        result["momentum_acceleration"] = r5 - r20 if "return_20d" in result.columns else r5 - r10

    if "sma_20" in result.columns and "sma_50" in result.columns:
        has_200 = "sma_200" in result.columns
        if has_200:
            bull = (result["sma_20"] > result["sma_50"]) & (result["sma_50"] > result["sma_200"])
            bear = (result["sma_20"] < result["sma_50"]) & (result["sma_50"] < result["sma_200"])
        else:
            bull = result["sma_20"] > result["sma_50"]
            bear = result["sma_20"] < result["sma_50"]
        result["market_regime_sma"] = 0
        result.loc[bull, "market_regime_sma"] = 1
        result.loc[bear, "market_regime_sma"] = -1

    if "adx_14" in result.columns:
        result["trend_strength"] = result["adx_14"].fillna(0)

    if "days_to_fomc" in result.columns:
        result["post_fomc_day"] = (-result["days_to_fomc"]).clip(lower=0)
    if "days_to_earnings" in result.columns:
        result["post_earnings_day"] = (-result["days_to_earnings"]).clip(lower=0)

    temporal_cols = [c for c in result.columns if c.startswith(("ticker_win_rate", "ticker_avg_pnl", "ticker_trade_count",
                     "streak_same_ticker", "days_since_last", "momentum_", "market_regime_sma", "trend_strength",
                     "post_fomc_day", "post_earnings_day"))]
    print(f"Added {len(temporal_cols)} temporal cross-trade features")

    # --- Candle windows (30 bars x 15 features per trade) ---
    candle_windows = _build_candle_windows(result, cache)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if candle_windows is not None:
        candle_out = output_path.parent / "candle_windows.npy"
        np.save(candle_out, candle_windows)
        print(f"Saved candle windows: shape={candle_windows.shape} to {candle_out}")

    result.to_parquet(output_path, index=False)
    print(f"Saved enriched data to {output_path}")

    try:
        from report_to_phoenix import report_progress
        report_progress("enrich", f"Enriched {len(result)} trades with {n_new_cols} attributes", 30, {
            "trades": len(result),
            "attributes_added": n_new_cols,
            "trades_enriched": n_success,
            "trades_skipped": n_empty,
        })
    except Exception:
        pass


def _build_candle_windows(df: pd.DataFrame, cache: dict) -> np.ndarray | None:
    """Build 30-bar x 15-feature candle windows for each trade."""
    BARS = 30
    FEATURES_PER_BAR = 15

    windows = []
    tickers = df["ticker"].values if "ticker" in df.columns else [None] * len(df)
    times = pd.to_datetime(df["entry_time"]) if "entry_time" in df.columns else [None] * len(df)

    for i in range(len(df)):
        ticker = tickers[i]
        entry_time = times[i] if times is not None else None

        if ticker is None or entry_time is None or pd.isna(entry_time):
            windows.append(np.zeros((BARS, FEATURES_PER_BAR), dtype=np.float32))
            continue

        cache_key = f"_intra5m_{ticker}"
        if cache_key not in cache:
            start = (entry_time - timedelta(days=5)).strftime("%Y-%m-%d")
            end = (entry_time + timedelta(days=1)).strftime("%Y-%m-%d")
            try:
                import yfinance as yf
                hist = yf.download(ticker, start=start, end=end, interval="5m", progress=False)
                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = hist.columns.get_level_values(0)
                cache[cache_key] = hist
            except Exception:
                cache[cache_key] = pd.DataFrame()

        hist = cache[cache_key]
        if hist.empty or len(hist) < BARS:
            windows.append(np.zeros((BARS, FEATURES_PER_BAR), dtype=np.float32))
            continue

        if hist.index.tz is not None:
            entry_tz = hist.index.tz
            if entry_time.tzinfo is None:
                entry_time = entry_time.tz_localize(entry_tz)
        mask = hist.index <= entry_time
        pre = hist[mask].tail(BARS)
        if len(pre) < BARS:
            windows.append(np.zeros((BARS, FEATURES_PER_BAR), dtype=np.float32))
            continue

        close = pre["Close"]
        high = pre["High"]
        low = pre["Low"]
        volume = pre["Volume"]

        rsi = _calc_rsi(close, 14).fillna(50)
        macd_line, macd_signal, _ = _calc_macd(close)
        ema9 = _calc_ema(close, 9)
        sma20 = _calc_sma(close, 20)
        atr = ((high - low).rolling(14).mean()).fillna(0)
        obv = (np.sign(close.diff().fillna(0)) * volume).cumsum()
        vwap = (close * volume).cumsum() / volume.cumsum().replace(0, np.nan)
        bb_upper = sma20 + 2 * close.rolling(20).std()
        bb_lower = sma20 - 2 * close.rolling(20).std()

        bar_data = np.column_stack([
            pre["Open"].values, high.values, low.values, close.values, volume.values,
            rsi.values, macd_line.values if hasattr(macd_line, "values") else np.zeros(BARS),
            macd_signal.values if hasattr(macd_signal, "values") else np.zeros(BARS),
            bb_upper.fillna(0).values, bb_lower.fillna(0).values,
            atr.values, obv.values, vwap.fillna(0).values, ema9.fillna(0).values, sma20.fillna(0).values,
        ])

        if bar_data.shape != (BARS, FEATURES_PER_BAR):
            windows.append(np.zeros((BARS, FEATURES_PER_BAR), dtype=np.float32))
        else:
            col_max = np.abs(bar_data).max(axis=0)
            col_max[col_max == 0] = 1
            windows.append((bar_data / col_max).astype(np.float32))

    return np.array(windows, dtype=np.float32)


if __name__ == "__main__":
    main()
