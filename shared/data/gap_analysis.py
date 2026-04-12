"""Time-series gap analysis features computed from OHLCV data.

Pure computation module -- no external API calls.  Operates on a pandas
DataFrame with columns: Open, High, Low, Close, Volume (standard yfinance
format).

Two entry points:
- ``compute_gap_features(df, as_of_idx)`` -- single-signal (returns dict)
- ``compute_gap_features_batch(df)`` -- backtest batch (returns DataFrame)
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Minimum gap threshold (0.05 %) to count as a real gap
_GAP_THRESHOLD = 0.0005
_LOOKBACK = 20


def _gap_series(df: pd.DataFrame) -> pd.Series:
    """Return per-bar gap percentage: (Open[i] - Close[i-1]) / Close[i-1]."""
    prev_close = df["Close"].shift(1)
    return (df["Open"] - prev_close) / prev_close.replace(0, np.nan)


def _gap_direction_series(gap_pct: pd.Series, threshold: float = _GAP_THRESHOLD) -> pd.Series:
    """1 for gap up, -1 for gap down, 0 for no gap."""
    direction = pd.Series(0, index=gap_pct.index, dtype=int)
    direction[gap_pct > threshold] = 1
    direction[gap_pct < -threshold] = -1
    return direction


def _gap_filled_series(df: pd.DataFrame, gap_pct: pd.Series) -> pd.Series:
    """1.0 if the gap was filled during the session, else 0.0."""
    prev_close = df["Close"].shift(1)
    filled = pd.Series(0.0, index=df.index)
    # Gap up: filled if today's low <= yesterday's close
    gap_up = gap_pct > _GAP_THRESHOLD
    filled[gap_up] = (df["Low"][gap_up] <= prev_close[gap_up]).astype(float)
    # Gap down: filled if today's high >= yesterday's close
    gap_down = gap_pct < -_GAP_THRESHOLD
    filled[gap_down] = (df["High"][gap_down] >= prev_close[gap_down]).astype(float)
    return filled


def _gap_fill_pct_series(df: pd.DataFrame, gap_pct: pd.Series) -> pd.Series:
    """Fraction of the gap that was filled (0-1)."""
    prev_close = df["Close"].shift(1)
    gap_size = (df["Open"] - prev_close).abs()
    fill_pct = pd.Series(0.0, index=df.index)

    gap_up = gap_pct > _GAP_THRESHOLD
    if gap_up.any():
        penetration = (df["Open"][gap_up] - df["Low"][gap_up]).clip(lower=0)
        fill_pct[gap_up] = (penetration / gap_size[gap_up].replace(0, np.nan)).clip(0, 1)

    gap_down = gap_pct < -_GAP_THRESHOLD
    if gap_down.any():
        penetration = (df["High"][gap_down] - df["Open"][gap_down]).clip(lower=0)
        fill_pct[gap_down] = (penetration / gap_size[gap_down].replace(0, np.nan)).clip(0, 1)

    return fill_pct.fillna(0.0)


def _is_weekend_gap(df: pd.DataFrame) -> pd.Series:
    """1.0 if the bar's date is >2 calendar days after the previous bar."""
    if not hasattr(df.index, 'to_series'):
        idx = pd.to_datetime(df.index)
    else:
        idx = df.index
    day_diff = pd.Series(idx, index=df.index).diff().dt.days
    return (day_diff > 2).astype(float)


def compute_gap_features(df: pd.DataFrame, as_of_idx: int | None = None) -> dict:
    """Compute gap-analysis features for a single point in time.

    Parameters
    ----------
    df : DataFrame
        OHLCV data with columns Open, High, Low, Close, Volume.
    as_of_idx : int or None
        Row index to treat as "today".  ``None`` means the last row.

    Returns
    -------
    dict
        Feature name -> float (or ``np.nan``).
    """
    try:
        return _compute_gap_features_at(df, as_of_idx)
    except Exception as exc:
        logger.warning("Gap feature computation failed: %s", exc)
        return _nan_dict()


def _compute_gap_features_at(df: pd.DataFrame, as_of_idx: int | None) -> dict:
    if df is None or len(df) < 2:
        return _nan_dict()

    # Slice up to (and including) as_of_idx
    if as_of_idx is not None:
        df = df.iloc[: as_of_idx + 1]

    if len(df) < 2:
        return _nan_dict()

    gap_pct = _gap_series(df)
    gap_dir = _gap_direction_series(gap_pct)
    gap_filled = _gap_filled_series(df, gap_pct)
    gap_fill_pct = _gap_fill_pct_series(df, gap_pct)
    weekend = _is_weekend_gap(df)

    features: dict[str, float] = {}

    # Current bar values
    features["gap_pct_new"] = _sf(gap_pct.iloc[-1])
    features["gap_direction"] = float(gap_dir.iloc[-1])
    features["gap_filled"] = float(gap_filled.iloc[-1])
    features["gap_fill_pct"] = _sf(gap_fill_pct.iloc[-1])
    features["weekend_gap"] = float(weekend.iloc[-1])
    features["overnight_return"] = _sf(gap_pct.iloc[-1])

    # Rolling 20-day window
    n = min(_LOOKBACK, len(gap_pct) - 1)  # -1 because first gap_pct is NaN
    if n < 2:
        features.update(_nan_rolling())
        return features

    recent_gap = gap_pct.iloc[-n:]
    recent_dir = gap_dir.iloc[-n:]
    recent_filled = gap_filled.iloc[-n:]

    # Average gap fill rate
    has_gap = recent_dir != 0
    gap_count = int(has_gap.sum())
    if gap_count > 0:
        features["avg_gap_fill_rate_20d"] = float(recent_filled[has_gap].mean())
    else:
        features["avg_gap_fill_rate_20d"] = np.nan

    # Gap persistence score: ratio of unfilled gaps
    if gap_count > 0:
        features["gap_persistence_score"] = float(1.0 - recent_filled[has_gap].mean())
    else:
        features["gap_persistence_score"] = np.nan

    # Consecutive gap days in same direction (from the end)
    consecutive = 0
    if len(recent_dir) >= 2:
        last_dir = recent_dir.iloc[-1]
        if last_dir != 0:
            for i in range(len(recent_dir) - 1, -1, -1):
                if recent_dir.iloc[i] == last_dir:
                    consecutive += 1
                else:
                    break
    features["consecutive_gap_days"] = float(consecutive)

    # ATR for normalization
    atr_14 = _calc_atr(df)
    if atr_14 > 0:
        features["gap_vs_atr_ratio"] = _sf(abs(gap_pct.iloc[-1]) * df["Close"].iloc[-1] / atr_14)
    else:
        features["gap_vs_atr_ratio"] = np.nan

    # Rolling stats
    abs_gaps = recent_gap.abs()
    features["avg_gap_size_20d"] = _sf(abs_gaps.mean())
    features["gap_std_20d"] = _sf(abs_gaps.std())

    # Z-score
    mean_g = abs_gaps.mean()
    std_g = abs_gaps.std()
    if std_g > 0 and not np.isnan(std_g):
        features["gap_zscore"] = _sf((abs(gap_pct.iloc[-1]) - mean_g) / std_g)
    else:
        features["gap_zscore"] = np.nan

    features["max_gap_20d"] = _sf(abs_gaps.max())

    # Gap reversal rate: how often gap direction reverses next day
    if len(recent_dir) >= 2:
        reversals = 0
        total_gaps_with_next = 0
        for i in range(len(recent_dir) - 1):
            if recent_dir.iloc[i] != 0 and recent_dir.iloc[i + 1] != 0:
                total_gaps_with_next += 1
                if recent_dir.iloc[i] != recent_dir.iloc[i + 1]:
                    reversals += 1
        if total_gaps_with_next > 0:
            features["gap_reversal_rate_20d"] = float(reversals / total_gaps_with_next)
        else:
            features["gap_reversal_rate_20d"] = np.nan
    else:
        features["gap_reversal_rate_20d"] = np.nan

    # Gap continuation: price continues in gap direction by close
    close_change = df["Close"].diff()
    recent_close_change = close_change.iloc[-n:]
    if gap_count > 0:
        continuation = 0
        for i in range(len(recent_dir)):
            if recent_dir.iloc[i] == 1 and recent_close_change.iloc[i] > 0:
                continuation += 1
            elif recent_dir.iloc[i] == -1 and recent_close_change.iloc[i] < 0:
                continuation += 1
        features["gap_continuation_pct"] = float(continuation / gap_count)
    else:
        features["gap_continuation_pct"] = np.nan

    return features


def compute_gap_features_batch(df: pd.DataFrame) -> pd.DataFrame:
    """Compute gap features for every row in the DataFrame (backtest mode).

    Returns a DataFrame with gap feature columns, same index as *df*.
    """
    if df is None or len(df) < 2:
        return pd.DataFrame(index=df.index if df is not None else [])

    try:
        return _batch_impl(df)
    except Exception as exc:
        logger.warning("Batch gap feature computation failed: %s", exc)
        return pd.DataFrame(index=df.index)


def _batch_impl(df: pd.DataFrame) -> pd.DataFrame:
    gap_pct = _gap_series(df)
    gap_dir = _gap_direction_series(gap_pct)
    gap_filled = _gap_filled_series(df, gap_pct)
    gap_fill_pct = _gap_fill_pct_series(df, gap_pct)
    weekend = _is_weekend_gap(df)

    result = pd.DataFrame(index=df.index)
    result["gap_pct_new"] = gap_pct
    result["gap_direction"] = gap_dir.astype(float)
    result["gap_filled"] = gap_filled
    result["gap_fill_pct"] = gap_fill_pct
    result["weekend_gap"] = weekend
    result["overnight_return"] = gap_pct

    # Rolling features (20-bar window)
    abs_gaps = gap_pct.abs()
    has_gap = (gap_dir != 0).astype(float)

    # Rolling fill rate: mean of gap_filled where there was a gap
    # We compute this carefully to handle division
    filled_where_gap = gap_filled * has_gap
    gap_count_roll = has_gap.rolling(_LOOKBACK, min_periods=2).sum()
    filled_count_roll = filled_where_gap.rolling(_LOOKBACK, min_periods=2).sum()
    result["avg_gap_fill_rate_20d"] = (filled_count_roll / gap_count_roll.replace(0, np.nan))

    result["gap_persistence_score"] = 1.0 - result["avg_gap_fill_rate_20d"]

    result["avg_gap_size_20d"] = abs_gaps.rolling(_LOOKBACK, min_periods=2).mean()
    result["gap_std_20d"] = abs_gaps.rolling(_LOOKBACK, min_periods=2).std()

    mean_roll = result["avg_gap_size_20d"]
    std_roll = result["gap_std_20d"]
    result["gap_zscore"] = (abs_gaps - mean_roll) / std_roll.replace(0, np.nan)

    result["max_gap_20d"] = abs_gaps.rolling(_LOOKBACK, min_periods=2).max()

    # ATR for gap_vs_atr_ratio
    atr = _calc_atr_series(df)
    result["gap_vs_atr_ratio"] = (abs_gaps * df["Close"]) / atr.replace(0, np.nan)

    # Consecutive gap days, reversal rate, continuation -- computed per-row
    consec = []
    reversal_rate = []
    continuation_pct = []
    close_change = df["Close"].diff()

    for i in range(len(df)):
        start = max(0, i - _LOOKBACK + 1)
        window_dir = gap_dir.iloc[start:i + 1]
        window_cc = close_change.iloc[start:i + 1]

        # Consecutive
        c = 0
        if len(window_dir) >= 1:
            last_d = window_dir.iloc[-1]
            if last_d != 0:
                for j in range(len(window_dir) - 1, -1, -1):
                    if window_dir.iloc[j] == last_d:
                        c += 1
                    else:
                        break
        consec.append(float(c))

        # Reversal rate
        w_gaps = window_dir[window_dir != 0]
        if len(w_gaps) >= 2:
            rev = sum(1 for k in range(len(w_gaps) - 1) if w_gaps.iloc[k] != w_gaps.iloc[k + 1])
            reversal_rate.append(rev / (len(w_gaps) - 1))
        else:
            reversal_rate.append(np.nan)

        # Continuation
        gc = int((window_dir != 0).sum())
        if gc > 0:
            cont = 0
            for k in range(len(window_dir)):
                d = window_dir.iloc[k]
                cc = window_cc.iloc[k]
                if d == 1 and cc > 0:
                    cont += 1
                elif d == -1 and cc < 0:
                    cont += 1
            continuation_pct.append(cont / gc)
        else:
            continuation_pct.append(np.nan)

    result["consecutive_gap_days"] = consec
    result["gap_reversal_rate_20d"] = reversal_rate
    result["gap_continuation_pct"] = continuation_pct

    return result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _sf(val: float) -> float:
    """Safe float -- returns np.nan for non-finite values."""
    try:
        v = float(val)
        return v if np.isfinite(v) else np.nan
    except (TypeError, ValueError):
        return np.nan


def _calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Return the most recent ATR(period) value."""
    if len(df) < period + 1:
        return 0.0
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    val = atr.iloc[-1]
    return float(val) if np.isfinite(val) else 0.0


def _calc_atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Return ATR(period) as a full series."""
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _nan_rolling() -> dict:
    """Return NaN for all rolling features."""
    return {
        "avg_gap_fill_rate_20d": np.nan,
        "gap_persistence_score": np.nan,
        "consecutive_gap_days": 0.0,
        "gap_vs_atr_ratio": np.nan,
        "avg_gap_size_20d": np.nan,
        "gap_std_20d": np.nan,
        "gap_zscore": np.nan,
        "max_gap_20d": np.nan,
        "gap_reversal_rate_20d": np.nan,
        "gap_continuation_pct": np.nan,
    }


def _nan_dict() -> dict:
    """Return NaN for all gap features."""
    return {
        "gap_pct_new": np.nan,
        "gap_direction": np.nan,
        "gap_filled": np.nan,
        "gap_fill_pct": np.nan,
        "weekend_gap": np.nan,
        "overnight_return": np.nan,
        **_nan_rolling(),
    }
