"""Real-time single-trade enrichment: fetch live market data and compute ~200 features.

Usage:
    python enrich_single.py --signal pending_signals.json --output enriched_signal.json
"""

import argparse
import calendar
import json
import logging
import sys
import warnings
from datetime import date, datetime, timezone
from pathlib import Path

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
    format="%(asctime)s [enrich] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

SECTOR_ETFS = {
    "XLF": "financials",
    "XLK": "technology",
    "XLE": "energy",
    "XLV": "healthcare",
    "XLI": "industrials",
    "XLP": "consumer_staples",
    "XLY": "consumer_disc",
    "XLU": "utilities",
    "XLRE": "real_estate",
    "XLB": "materials",
    "XLC": "communication",
}

MARKET_ETFS = ["SPY", "QQQ", "IWM", "DIA"]

# ---------------------------------------------------------------------------
# Technical indicator helpers
# ---------------------------------------------------------------------------

def _safe_download(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    if yf is None:
        return pd.DataFrame()
    try:
        data = yf.download(ticker, period=period, interval=interval, progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        return data
    except Exception as exc:
        log.warning("Download failed for %s: %s", ticker, exc)
        return pd.DataFrame()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
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


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    atr_vals = _atr(high, low, close, period)
    plus_di = 100 * _ema(plus_dm, period) / atr_vals.replace(0, np.nan)
    minus_di = 100 * _ema(minus_dm, period) / atr_vals.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return _ema(dx, period)


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                k_period: int = 14, d_period: int = 3):
    lowest = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    k = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


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
    if series.empty:
        return np.nan
    val = series.iloc[-1]
    return float(val) if not np.isnan(val) else np.nan


# ---------------------------------------------------------------------------
# Core enrichment
# ---------------------------------------------------------------------------

def enrich_signal(signal: dict) -> dict:
    """Enrich a single signal dict with ~200 real-time market features."""
    ticker = signal.get("ticker", "SPY")
    now = datetime.now(timezone.utc)
    attrs = {}

    cache: dict[str, pd.DataFrame] = {}

    def _get(tkr: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        key = f"{tkr}_{period}_{interval}"
        if key not in cache:
            cache[key] = _safe_download(tkr, period=period, interval=interval)
        return cache[key]

    # -- Underlying daily data --
    hist = _get(ticker, period="2y", interval="1d")
    if hist.empty or len(hist) < 20:
        log.warning("Insufficient data for %s (%d bars)", ticker, len(hist))
        attrs["enrichment_error"] = f"Insufficient data for {ticker}"
        attrs.update(signal)
        return attrs

    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]
    opn = hist["Open"]

    # ── 1. Price Action ──────────────────────────────────────────────────
    attrs["last_close"] = _last(close)
    for d in [1, 3, 5, 10, 20, 60]:
        if len(close) > d:
            attrs[f"return_{d}d"] = float((close.iloc[-1] - close.iloc[-min(d + 1, len(close))]) /
                                          close.iloc[-min(d + 1, len(close))])
        else:
            attrs[f"return_{d}d"] = np.nan

    if len(close) >= 2:
        attrs["gap_pct"] = float((opn.iloc[-1] - close.iloc[-2]) / close.iloc[-2])
        attrs["range_pct"] = float((high.iloc[-1] - low.iloc[-1]) / close.iloc[-1])
        attrs["body_pct"] = float(abs(close.iloc[-1] - opn.iloc[-1]) / close.iloc[-1])

    atr_vals = _atr(high, low, close)
    attrs["atr_14"] = _last(atr_vals)
    attrs["atr_pct"] = attrs["atr_14"] / attrs["last_close"] if attrs["last_close"] else np.nan

    for d in [5, 10, 20]:
        if len(high) >= d:
            attrs[f"high_{d}d"] = float(high.iloc[-d:].max())
            attrs[f"low_{d}d"] = float(low.iloc[-d:].min())

    if len(close) >= 252:
        h52 = float(high.iloc[-252:].max())
        l52 = float(low.iloc[-252:].min())
        attrs["dist_from_52w_high"] = (attrs["last_close"] - h52) / h52
        attrs["dist_from_52w_low"] = (attrs["last_close"] - l52) / l52

    greens = 0
    for i in range(2, min(11, len(close) + 1)):
        if close.iloc[-i] < close.iloc[-i + 1]:
            greens += 1
        else:
            break
    attrs["consecutive_green"] = greens

    # Fibonacci retracement levels relative to 20d range
    if len(high) >= 20:
        h20 = float(high.iloc[-20:].max())
        l20 = float(low.iloc[-20:].min())
        rng = h20 - l20
        if rng > 0:
            for fib_level in [0.236, 0.382, 0.5, 0.618, 0.786]:
                fib_price = h20 - fib_level * rng
                attrs[f"fib_{str(fib_level).replace('.', '')}"] = fib_price
                attrs[f"dist_fib_{str(fib_level).replace('.', '')}"] = (attrs["last_close"] - fib_price) / attrs["last_close"]

    # Higher highs / lower lows count
    for lookback in [5, 10]:
        if len(high) > lookback:
            hh = sum(1 for j in range(1, lookback) if high.iloc[-j] > high.iloc[-j - 1])
            ll = sum(1 for j in range(1, lookback) if low.iloc[-j] < low.iloc[-j - 1])
            attrs[f"higher_highs_{lookback}d"] = hh
            attrs[f"lower_lows_{lookback}d"] = ll

    # Inside bar / candle patterns
    if len(high) >= 2:
        attrs["inside_bar"] = float(high.iloc[-1] <= high.iloc[-2] and low.iloc[-1] >= low.iloc[-2])
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

    # ── 2. Technical Indicators ──────────────────────────────────────────
    for p in [7, 14, 21]:
        attrs[f"rsi_{p}"] = _last(_rsi(close, p))

    macd_line, macd_sig, macd_hist = _macd(close)
    attrs["macd_line"] = _last(macd_line)
    attrs["macd_signal"] = _last(macd_sig)
    attrs["macd_histogram"] = _last(macd_hist)
    if len(macd_line) >= 2:
        attrs["macd_cross_up"] = int(macd_line.iloc[-1] > macd_sig.iloc[-1] and
                                     macd_line.iloc[-2] <= macd_sig.iloc[-2])
        attrs["macd_cross_down"] = int(macd_line.iloc[-1] < macd_sig.iloc[-1] and
                                       macd_line.iloc[-2] >= macd_sig.iloc[-2])

    bb_upper, bb_mid, bb_lower = _bollinger(close)
    attrs["bb_upper"] = _last(bb_upper)
    attrs["bb_middle"] = _last(bb_mid)
    attrs["bb_lower"] = _last(bb_lower)
    if attrs["bb_upper"] and attrs["bb_lower"] and (attrs["bb_upper"] - attrs["bb_lower"]) != 0:
        attrs["bb_position"] = (attrs["last_close"] - attrs["bb_lower"]) / (attrs["bb_upper"] - attrs["bb_lower"])
        attrs["bb_width"] = (attrs["bb_upper"] - attrs["bb_lower"]) / attrs["bb_middle"] if attrs["bb_middle"] else np.nan

    stoch_k, stoch_d = _stochastic(high, low, close)
    attrs["stoch_k"] = _last(stoch_k)
    attrs["stoch_d"] = _last(stoch_d)

    srsi_k, srsi_d = _stochastic_rsi(close)
    attrs["stoch_rsi_k"] = _last(srsi_k)
    attrs["stoch_rsi_d"] = _last(srsi_d)

    attrs["adx_14"] = _last(_adx(high, low, close))

    cci_period = 20
    if len(close) >= cci_period:
        tp = (high + low + close) / 3
        sma_tp = tp.rolling(cci_period).mean()
        mad = tp.rolling(cci_period).apply(lambda x: np.abs(x - x.mean()).mean())
        attrs["cci_20"] = float((tp.iloc[-1] - sma_tp.iloc[-1]) / (0.015 * mad.iloc[-1])) if mad.iloc[-1] != 0 else np.nan

    obv_vals = _obv(close, volume)
    attrs["obv"] = _last(obv_vals)
    attrs["obv_slope_5"] = float(obv_vals.iloc[-1] - obv_vals.iloc[-min(6, len(obv_vals))]) / 5 if len(obv_vals) >= 5 else np.nan
    attrs["obv_slope_20"] = float(obv_vals.iloc[-1] - obv_vals.iloc[-min(21, len(obv_vals))]) / 20 if len(obv_vals) >= 20 else np.nan

    # Williams %R
    if len(close) >= 14:
        highest14 = high.rolling(14).max()
        lowest14 = low.rolling(14).min()
        wr = -100 * (highest14.iloc[-1] - close.iloc[-1]) / (highest14.iloc[-1] - lowest14.iloc[-1]) if (highest14.iloc[-1] - lowest14.iloc[-1]) > 0 else np.nan
        attrs["williams_r_14"] = float(wr)

    # Rate of Change
    for roc_d in [5, 10]:
        if len(close) > roc_d:
            attrs[f"roc_{roc_d}d"] = float((close.iloc[-1] - close.iloc[-roc_d - 1]) / close.iloc[-roc_d - 1])

    # Money Flow Index
    if len(close) >= 15:
        tp = (high + low + close) / 3
        mf = tp * volume
        pos_mf = mf.where(tp.diff() > 0, 0.0).rolling(14).sum()
        neg_mf = mf.where(tp.diff() <= 0, 0.0).rolling(14).sum()
        mfi = 100 - (100 / (1 + pos_mf / neg_mf.replace(0, np.nan)))
        attrs["mfi_14"] = _last(mfi)

    # TRIX (15)
    if len(close) >= 45:
        ema1 = _ema(close, 15)
        ema2 = _ema(ema1, 15)
        ema3 = _ema(ema2, 15)
        attrs["trix_15"] = float(((ema3.iloc[-1] - ema3.iloc[-2]) / ema3.iloc[-2]) * 100) if ema3.iloc[-2] != 0 else np.nan

    # Keltner Channel
    if len(close) >= 20:
        kc_mid = _ema(close, 20)
        kc_atr = _atr(high, low, close, 10)
        kc_upper = kc_mid + 2 * kc_atr
        kc_lower = kc_mid - 2 * kc_atr
        attrs["keltner_upper"] = _last(kc_upper)
        attrs["keltner_lower"] = _last(kc_lower)
        kc_range = kc_upper.iloc[-1] - kc_lower.iloc[-1]
        attrs["keltner_position"] = float((close.iloc[-1] - kc_lower.iloc[-1]) / kc_range) if kc_range > 0 else np.nan

    # Donchian Channel (20d)
    if len(high) >= 20:
        dc_upper = float(high.rolling(20).max().iloc[-1])
        dc_lower = float(low.rolling(20).min().iloc[-1])
        attrs["donchian_upper"] = dc_upper
        attrs["donchian_lower"] = dc_lower
        dc_range = dc_upper - dc_lower
        attrs["donchian_position"] = float((close.iloc[-1] - dc_lower) / dc_range) if dc_range > 0 else np.nan

    # Ichimoku (simplified)
    if len(close) >= 52:
        tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
        kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
        senkou_a = ((tenkan + kijun) / 2).shift(26)
        senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
        attrs["ichimoku_tenkan"] = _last(tenkan)
        attrs["ichimoku_kijun"] = _last(kijun)
        attrs["ichimoku_above_cloud"] = float(
            close.iloc[-1] > max(senkou_a.iloc[-1], senkou_b.iloc[-1])
        ) if not (np.isnan(senkou_a.iloc[-1]) or np.isnan(senkou_b.iloc[-1])) else np.nan

    # Parabolic SAR direction (simplified)
    if len(close) >= 5:
        attrs["parabolic_sar_bullish"] = float(close.iloc[-1] > close.iloc[-3])

    # CMF (20)
    if len(close) >= 20:
        clv = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
        cmf = (clv * volume).rolling(20).sum() / volume.rolling(20).sum().replace(0, np.nan)
        attrs["cmf_20"] = _last(cmf)

    # ── 3. Moving Averages ───────────────────────────────────────────────
    for w in [5, 10, 20, 50, 100, 200]:
        sma_val = _sma(close, w)
        ema_val = _ema(close, w)
        attrs[f"sma_{w}"] = _last(sma_val) if len(close) >= w else np.nan
        attrs[f"ema_{w}"] = _last(ema_val) if len(close) >= w else np.nan

    for w in [20, 50, 200]:
        sv = attrs.get(f"sma_{w}", np.nan)
        if sv and not np.isnan(sv) and sv != 0:
            attrs[f"dist_sma_{w}"] = (attrs["last_close"] - sv) / sv

    sma20 = attrs.get("sma_20", np.nan)
    sma50 = attrs.get("sma_50", np.nan)
    sma200 = attrs.get("sma_200", np.nan)

    def _safe_gt(a, b):
        if a is None or b is None:
            return np.nan
        if np.isnan(a) or np.isnan(b):
            return np.nan
        return float(a > b)

    attrs["sma_20_above_50"] = _safe_gt(sma20, sma50)
    attrs["sma_50_above_200"] = _safe_gt(sma50, sma200)
    attrs["price_above_sma20"] = _safe_gt(attrs["last_close"], sma20)
    attrs["price_above_sma50"] = _safe_gt(attrs["last_close"], sma50)
    attrs["price_above_sma200"] = _safe_gt(attrs["last_close"], sma200)

    # ── 4. Volume ────────────────────────────────────────────────────────
    attrs["volume_last"] = float(volume.iloc[-1]) if not volume.empty else np.nan
    for w in [5, 10, 20]:
        vol_sma = _sma(volume, w)
        attrs[f"volume_sma_{w}"] = _last(vol_sma) if len(volume) >= w else np.nan
    if attrs.get("volume_sma_20") and attrs["volume_sma_20"] > 0:
        attrs["volume_ratio_20"] = attrs["volume_last"] / attrs["volume_sma_20"]
        attrs["volume_breakout"] = float(attrs["volume_ratio_20"] > 2.0)
    if attrs.get("volume_sma_5") and attrs["volume_sma_5"] > 0:
        attrs["volume_ratio_5"] = attrs["volume_last"] / attrs["volume_sma_5"]

    if len(volume) >= 20:
        vol_std = volume.iloc[-20:].std()
        vol_mean = volume.iloc[-20:].mean()
        attrs["volume_zscore"] = float((volume.iloc[-1] - vol_mean) / vol_std) if vol_std > 0 else 0.0

    # Up-volume ratio (5d)
    if len(close) >= 5:
        up_days = sum(1 for j in range(1, 6) if close.iloc[-j] > opn.iloc[-j])
        attrs["up_volume_ratio_5d"] = up_days / 5.0

    # AD line
    if len(close) >= 2:
        clv_vol = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
        ad_line = (clv_vol.fillna(0) * volume).cumsum()
        attrs["ad_line"] = _last(ad_line)

    # Force Index (13)
    if len(close) >= 14:
        force = close.diff() * volume
        force_ema = _ema(force.fillna(0), 13)
        attrs["force_index_13"] = _last(force_ema)

    # ── 5. Volatility ───────────────────────────────────────────────────
    log_returns = np.log(close / close.shift(1)).dropna()
    for w in [5, 10, 20, 60]:
        if len(log_returns) >= w:
            attrs[f"realized_vol_{w}d"] = float(log_returns.iloc[-w:].std() * np.sqrt(252))

    if attrs.get("realized_vol_5d") and attrs.get("realized_vol_20d") and attrs["realized_vol_20d"] > 0:
        attrs["vol_ratio_5_20"] = attrs["realized_vol_5d"] / attrs["realized_vol_20d"]

    if len(close) >= 20:
        attrs["parkinson_vol"] = float(np.sqrt(
            (1 / (4 * len(high.iloc[-20:]) * np.log(2))) *
            ((np.log(high.iloc[-20:] / low.iloc[-20:])) ** 2).sum()
        ) * np.sqrt(252))

    # Garman-Klass volatility (20d)
    if len(close) >= 21:
        gc_close = close.iloc[-21:]
        gc_high = high.iloc[-21:]
        gc_low = low.iloc[-21:]
        gc_open = opn.iloc[-21:]
        hl = np.log(gc_high.iloc[1:].values / gc_low.iloc[1:].values) ** 2
        co = np.log(gc_close.iloc[1:].values / gc_open.iloc[1:].values) ** 2
        attrs["garman_klass_vol"] = float(np.sqrt((0.5 * hl - (2 * np.log(2) - 1) * co).mean()) * np.sqrt(252))

    # ATR percentile (30d)
    atr_series = _atr(high, low, close)
    if len(atr_series) >= 30:
        attrs["atr_percentile_30d"] = float((atr_series.iloc[-30:] < atr_series.iloc[-1]).mean())

    # ── 6. Market Context ────────────────────────────────────────────────
    for etf in MARKET_ETFS:
        ctx = _get(etf, period="1mo", interval="1d")
        if not ctx.empty and len(ctx) >= 2:
            prefix = etf.lower()
            attrs[f"{prefix}_last"] = float(ctx["Close"].iloc[-1])
            attrs[f"{prefix}_return_1d"] = float((ctx["Close"].iloc[-1] - ctx["Close"].iloc[-2]) / ctx["Close"].iloc[-2])
            if len(ctx) >= 6:
                attrs[f"{prefix}_return_5d"] = float((ctx["Close"].iloc[-1] - ctx["Close"].iloc[-6]) / ctx["Close"].iloc[-6])

    # VIX
    vix = _get("^VIX", period="3mo", interval="1d")
    if not vix.empty and len(vix) >= 2:
        attrs["vix_level"] = float(vix["Close"].iloc[-1])
        attrs["vix_change_1d"] = float(vix["Close"].iloc[-1] - vix["Close"].iloc[-2])
        if len(vix) >= 5:
            attrs["vix_change_5d"] = float(vix["Close"].iloc[-1] - vix["Close"].iloc[-6])
        if len(vix) >= 30:
            attrs["vix_percentile_30d"] = float((vix["Close"].iloc[-30:] < vix["Close"].iloc[-1]).mean())
        attrs["vix_above_20"] = float(vix["Close"].iloc[-1] > 20)
        attrs["vix_above_30"] = float(vix["Close"].iloc[-1] > 30)

    # SPY correlation
    spy_data = _get("SPY", period="3mo", interval="1d")
    if not spy_data.empty and len(close) >= 20 and len(spy_data) >= 20:
        spy_close = spy_data["Close"]
        common_idx = close.index.intersection(spy_close.index)[-20:]
        if len(common_idx) >= 10:
            attrs["corr_spy_20d"] = float(
                close.loc[common_idx].pct_change().corr(spy_close.loc[common_idx].pct_change())
            )

    # Sector ETFs
    for etf_ticker, sector_name in SECTOR_ETFS.items():
        sect = _get(etf_ticker, period="5d", interval="1d")
        if not sect.empty and len(sect) >= 2:
            attrs[f"sector_{sector_name}_1d"] = float(
                (sect["Close"].iloc[-1] - sect["Close"].iloc[-2]) / sect["Close"].iloc[-2]
            )

    # Fixed income / gold proxies
    for proxy_ticker, proxy_prefix in [("TLT", "tlt"), ("GLD", "gld")]:
        p_data = _get(proxy_ticker, period="5d", interval="1d")
        if not p_data.empty and len(p_data) >= 2:
            attrs[f"{proxy_prefix}_return_1d"] = float(
                (p_data["Close"].iloc[-1] - p_data["Close"].iloc[-2]) / p_data["Close"].iloc[-2]
            )

    # ── 7. Time Features ────────────────────────────────────────────────
    entry_time = signal.get("timestamp")
    if entry_time:
        try:
            et = pd.Timestamp(entry_time)
        except Exception:
            et = now
    else:
        et = now

    if hasattr(et, "hour"):
        attrs["hour_of_day"] = et.hour
        attrs["minute_of_hour"] = et.minute
        attrs["is_pre_market"] = float(et.hour < 9 or (et.hour == 9 and et.minute < 30))
        attrs["is_first_hour"] = float(et.hour == 9 or (et.hour == 10 and et.minute <= 30))
        attrs["is_last_hour"] = float(et.hour == 15)
        attrs["is_power_hour"] = float(et.hour == 15 and et.minute >= 0)

    entry_date = et.date() if hasattr(et, "date") and callable(et.date) else date.today()
    attrs["day_of_week"] = entry_date.weekday()
    attrs["is_monday"] = float(entry_date.weekday() == 0)
    attrs["is_friday"] = float(entry_date.weekday() == 4)
    attrs["month"] = entry_date.month
    attrs["quarter"] = (entry_date.month - 1) // 3 + 1
    attrs["day_of_month"] = entry_date.day

    # OPEX calculation
    try:
        c = calendar.Calendar()
        fridays = [d for d in c.itermonthdays2(entry_date.year, entry_date.month)
                   if d[0] != 0 and d[1] == 4]
        opex_day = fridays[2][0] if len(fridays) >= 3 else 20
        opex_date = date(entry_date.year, entry_date.month, opex_day)
        attrs["days_to_opex"] = (opex_date - entry_date).days
        attrs["is_opex_week"] = float(abs(attrs["days_to_opex"]) <= 5)
    except Exception:
        attrs["days_to_opex"] = np.nan
        attrs["is_opex_week"] = np.nan

    # ── 8. Sentiment & Events ────────────────────────────────────────────
    # FinBERT sentiment on the original Discord message
    msg_text = signal.get("raw_message", signal.get("content", ""))
    if msg_text:
        try:
            from shared.nlp.sentiment_classifier import SentimentClassifier
            _clf = SentimentClassifier()
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

    # Earnings calendar
    if yf is not None:
        try:
            yf_ticker = yf.Ticker(ticker)
            cal = yf_ticker.calendar
            if cal is not None and not (isinstance(cal, pd.DataFrame) and cal.empty):
                if isinstance(cal, dict):
                    earn_date = cal.get("Earnings Date")
                    if isinstance(earn_date, list) and earn_date:
                        earn_date = earn_date[0]
                    if earn_date:
                        earn_dt = pd.Timestamp(earn_date).date()
                        attrs["days_to_earnings"] = (earn_dt - entry_date).days
                        attrs["earnings_within_7d"] = float(abs(attrs["days_to_earnings"]) <= 7)
                        attrs["earnings_within_14d"] = float(abs(attrs["days_to_earnings"]) <= 14)
                elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                    earn_date = cal.loc["Earnings Date"].iloc[0]
                    if earn_date:
                        earn_dt = pd.Timestamp(earn_date).date()
                        attrs["days_to_earnings"] = (earn_dt - entry_date).days
                        attrs["earnings_within_7d"] = float(abs(attrs["days_to_earnings"]) <= 7)
                        attrs["earnings_within_14d"] = float(abs(attrs["days_to_earnings"]) <= 14)
            # Analyst recommendations
            recs = yf_ticker.recommendations
            if recs is not None and not recs.empty:
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
        "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16",
    ]
    cpi_dates = [
        "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-10",
        "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
        "2026-09-11", "2026-10-13", "2026-11-10", "2026-12-10",
    ]
    nfp_dates = [
        "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03",
        "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07",
        "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
    ]
    for name, dates in [("fomc", fomc_dates), ("cpi", cpi_dates), ("nfp", nfp_dates)]:
        future = [d for d in (date.fromisoformat(d) for d in dates) if d >= entry_date]
        if future:
            days_away = (future[0] - entry_date).days
            attrs[f"days_to_{name}"] = days_away
            attrs[f"{name}_within_3d"] = float(days_away <= 3)

    # Quad witching (3rd Friday of Mar/Jun/Sep/Dec)
    if entry_date.month in (3, 6, 9, 12):
        try:
            c_cal = calendar.Calendar()
            fridays_qw = [d for d in c_cal.itermonthdays2(entry_date.year, entry_date.month)
                          if d[0] != 0 and d[1] == 4]
            qw_day = fridays_qw[2][0] if len(fridays_qw) >= 3 else 20
            qw_date = date(entry_date.year, entry_date.month, qw_day)
            attrs["is_quad_witching_week"] = float(abs((qw_date - entry_date).days) <= 5)
        except Exception:
            attrs["is_quad_witching_week"] = 0.0
    else:
        attrs["is_quad_witching_week"] = 0.0

    # ── 9. Options Data (Unusual Whales / yfinance) ───────────────────
    try:
        import asyncio
        from shared.unusual_whales.client import UnusualWhalesClient
        uw = UnusualWhalesClient()
        _loop = asyncio.new_event_loop()
        try:
            flow = _loop.run_until_complete(uw.get_options_flow(ticker=ticker))
            if flow:
                total_premium = sum(float(f.premium or 0) for f in flow[:50])
                call_premium = sum(float(f.premium or 0) for f in flow[:50]
                                   if f.option_type == "CALL")
                put_premium = total_premium - call_premium
                attrs["options_total_premium_50"] = total_premium
                attrs["options_call_premium_pct"] = call_premium / total_premium if total_premium > 0 else 0.5
                attrs["options_put_call_ratio"] = put_premium / call_premium if call_premium > 0 else np.nan
                attrs["options_flow_count"] = len(flow)
            gex = _loop.run_until_complete(uw.get_gex(ticker))
            if gex and gex.total_gex is not None:
                attrs["gex_value"] = float(gex.total_gex)
                attrs["gex_positive"] = float(attrs.get("gex_value", 0) > 0)
            try:
                chain = _loop.run_until_complete(uw.get_option_chain(ticker))
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
                    entry_px = float(signal.get("entry_price", 0))
                    atm = [c for c in contracts if entry_px > 0 and
                           abs(c.strike - entry_px) < entry_px * 0.05]
                    if not atm:
                        atm = contracts[:5]
                    if atm:
                        attrs["avg_delta"] = np.mean([c.delta or 0 for c in atm])
                        attrs["avg_gamma"] = np.mean([c.gamma or 0 for c in atm])
                        attrs["avg_theta"] = np.mean([c.theta or 0 for c in atm])
                        attrs["avg_vega"] = np.mean([c.vega or 0 for c in atm])
            except Exception:
                pass
        finally:
            _loop.close()
    except Exception:
        pass

    # ── 10. Intraday features (5m bars if available) ───────────────────
    intraday = _get(ticker, period="5d", interval="5m")
    if not intraday.empty and len(intraday) >= 20:
        ic = intraday["Close"]
        attrs["intraday_rsi_14"] = _last(_rsi(ic, 14))
        m_line, m_sig, m_hist = _macd(ic)
        attrs["intraday_macd_hist"] = _last(m_hist)
        attrs["intraday_vwap"] = float(
            (ic * intraday["Volume"]).sum() / intraday["Volume"].sum()
        ) if intraday["Volume"].sum() > 0 else np.nan
        attrs["price_vs_vwap"] = (ic.iloc[-1] - attrs["intraday_vwap"]) / attrs["intraday_vwap"] if attrs["intraday_vwap"] else np.nan

    # ── Merge original signal fields ─────────────────────────────────────
    result = {**signal, **attrs}

    # Convert numpy types for JSON serialization
    for k, v in result.items():
        if isinstance(v, (np.floating, np.float64, np.float32)):
            result[k] = None if np.isnan(v) else round(float(v), 6)
        elif isinstance(v, (np.integer, np.int64, np.int32)):
            result[k] = int(v)
        elif isinstance(v, (np.bool_,)):
            result[k] = bool(v)

    return result


def main():
    parser = argparse.ArgumentParser(description="Real-time single-trade enrichment")
    parser.add_argument("--signal", required=True, help="Path to pending_signals.json")
    parser.add_argument("--output", default="enriched_signal.json", help="Output path")
    parser.add_argument("--index", type=int, default=0,
                        help="Which signal to enrich if the file contains an array")
    args = parser.parse_args()

    signal_path = Path(args.signal)
    if not signal_path.exists():
        log.error("Signal file not found: %s", args.signal)
        sys.exit(1)

    with open(signal_path) as f:
        raw = json.load(f)

    if isinstance(raw, list):
        if args.index >= len(raw):
            log.error("Index %d out of range (file has %d signals)", args.index, len(raw))
            sys.exit(1)
        signal = raw[args.index]
        log.info("Enriching signal %d of %d", args.index + 1, len(raw))
    else:
        signal = raw

    log.info("Enriching signal for ticker=%s", signal.get("ticker", "unknown"))
    enriched = enrich_signal(signal)

    feature_count = len([k for k in enriched if k not in signal])
    log.info("Computed %d features", feature_count)

    with open(args.output, "w") as f:
        json.dump(enriched, f, indent=2, default=str)

    print(json.dumps({"status": "ok", "features_added": feature_count, "output": args.output}))


if __name__ == "__main__":
    main()
