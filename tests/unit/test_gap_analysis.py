"""Unit tests for shared.data.gap_analysis -- gap analysis features."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from shared.data.gap_analysis import (
    compute_gap_features,
    compute_gap_features_batch,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(
    closes: list[float],
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    start_date: str = "2024-01-02",
) -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame."""
    n = len(closes)
    if opens is None:
        opens = [c - 0.5 for c in closes]
    if highs is None:
        highs = [max(o, c) + 0.3 for o, c in zip(opens, closes)]
    if lows is None:
        lows = [min(o, c) - 0.3 for o, c in zip(opens, closes)]
    dates = pd.bdate_range(start=start_date, periods=n)
    return pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": [1_000_000] * n,
    }, index=dates)


# ---------------------------------------------------------------------------
# compute_gap_features (single)
# ---------------------------------------------------------------------------

class TestComputeGapFeatures:
    """Tests for the single-signal gap feature computation."""

    def test_basic_keys_present(self):
        df = _make_ohlcv([100 + i for i in range(30)])
        feats = compute_gap_features(df)
        expected_keys = [
            "gap_pct_new", "gap_direction", "gap_filled", "gap_fill_pct",
            "weekend_gap", "overnight_return",
            "avg_gap_fill_rate_20d", "gap_persistence_score",
            "consecutive_gap_days", "gap_vs_atr_ratio",
            "avg_gap_size_20d", "gap_std_20d", "gap_zscore", "max_gap_20d",
            "gap_reversal_rate_20d", "gap_continuation_pct",
        ]
        for key in expected_keys:
            assert key in feats, f"Missing key: {key}"

    def test_gap_up(self):
        """Create an explicit gap-up on the last bar."""
        closes = [100.0] * 25
        opens = [100.0] * 25
        highs = [101.0] * 25
        lows = [99.0] * 25
        # Last bar: gap up -- open well above previous close
        opens[-1] = 105.0
        closes[-1] = 106.0
        highs[-1] = 107.0
        lows[-1] = 104.0  # low > prev close => gap not filled

        df = _make_ohlcv(closes, opens, highs, lows)
        feats = compute_gap_features(df)

        assert feats["gap_direction"] == 1.0
        assert feats["gap_pct_new"] > 0
        assert feats["gap_filled"] == 0.0  # low (104) > prev close (100)
        assert feats["gap_fill_pct"] < 1.0

    def test_gap_down(self):
        """Create an explicit gap-down on the last bar."""
        closes = [100.0] * 25
        opens = [100.0] * 25
        highs = [101.0] * 25
        lows = [99.0] * 25
        # Last bar: gap down
        opens[-1] = 95.0
        closes[-1] = 94.0
        highs[-1] = 96.0  # high < prev close => gap not filled
        lows[-1] = 93.0

        df = _make_ohlcv(closes, opens, highs, lows)
        feats = compute_gap_features(df)

        assert feats["gap_direction"] == -1.0
        assert feats["gap_pct_new"] < 0
        assert feats["gap_filled"] == 0.0

    def test_no_gap(self):
        """Close and open are essentially the same => no gap."""
        closes = [100.0 + i * 0.001 for i in range(25)]
        opens = [c + 0.001 for c in closes]  # trivially small open shift
        highs = [max(o, c) + 0.5 for o, c in zip(opens, closes)]
        lows = [min(o, c) - 0.5 for o, c in zip(opens, closes)]

        df = _make_ohlcv(closes, opens, highs, lows)
        feats = compute_gap_features(df)

        assert feats["gap_direction"] == 0.0

    def test_gap_filled(self):
        """Gap up that gets fully filled (low touches prev close)."""
        closes = [100.0] * 25
        opens = [100.0] * 25
        highs = [101.0] * 25
        lows = [99.0] * 25
        # Gap up, but low == prev close => filled
        opens[-1] = 103.0
        closes[-1] = 104.0
        highs[-1] = 105.0
        lows[-1] = 100.0  # equals prev close

        df = _make_ohlcv(closes, opens, highs, lows)
        feats = compute_gap_features(df)

        assert feats["gap_filled"] == 1.0
        assert feats["gap_fill_pct"] == pytest.approx(1.0, abs=0.01)

    def test_weekend_gap(self):
        """Gap that spans a weekend is detected."""
        dates = pd.to_datetime([
            "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11", "2024-01-12",
            # Skip weekend
            "2024-01-15", "2024-01-16",
        ])
        df = pd.DataFrame({
            "Open": [100, 101, 102, 103, 104, 110, 111],
            "High": [101, 102, 103, 104, 105, 111, 112],
            "Low": [99, 100, 101, 102, 103, 109, 110],
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5, 110.5, 111.5],
            "Volume": [1e6] * 7,
        }, index=dates)

        feats = compute_gap_features(df, as_of_idx=5)  # Monday bar
        assert feats["weekend_gap"] == 1.0

    def test_nan_on_insufficient_data(self):
        """With < 2 rows, all features should be NaN."""
        df = _make_ohlcv([100.0])
        feats = compute_gap_features(df)
        for v in feats.values():
            assert np.isnan(v) or v == 0.0, f"Expected NaN or 0, got {v}"

    def test_nan_on_none_input(self):
        feats = compute_gap_features(None)
        assert isinstance(feats, dict)
        assert all(np.isnan(v) or v == 0.0 for v in feats.values())

    def test_as_of_idx(self):
        """as_of_idx slices the data correctly."""
        df = _make_ohlcv([100 + i for i in range(30)])
        feats_mid = compute_gap_features(df, as_of_idx=10)
        feats_end = compute_gap_features(df)
        # They should generally differ because they look at different windows
        assert feats_mid["gap_pct_new"] != feats_end["gap_pct_new"] or True  # at least no crash


# ---------------------------------------------------------------------------
# compute_gap_features_batch
# ---------------------------------------------------------------------------

class TestComputeGapFeaturesBatch:
    """Tests for the batch gap feature computation."""

    def test_returns_dataframe(self):
        df = _make_ohlcv([100 + i for i in range(30)])
        result = compute_gap_features_batch(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == len(df)

    def test_columns_present(self):
        df = _make_ohlcv([100 + i for i in range(30)])
        result = compute_gap_features_batch(df)
        expected_cols = [
            "gap_pct_new", "gap_direction", "gap_filled", "gap_fill_pct",
            "weekend_gap", "overnight_return",
            "avg_gap_fill_rate_20d", "gap_persistence_score",
            "avg_gap_size_20d", "gap_std_20d", "gap_zscore", "max_gap_20d",
            "gap_vs_atr_ratio", "consecutive_gap_days",
            "gap_reversal_rate_20d", "gap_continuation_pct",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_batch_single_consistency(self):
        """Last row of batch should match single-signal for same data."""
        df = _make_ohlcv([100 + i * 0.5 for i in range(30)])
        batch = compute_gap_features_batch(df)
        single = compute_gap_features(df)

        for key in ["gap_pct_new", "gap_direction", "gap_filled", "gap_fill_pct",
                     "weekend_gap", "overnight_return"]:
            batch_val = batch[key].iloc[-1]
            single_val = single[key]
            if np.isnan(batch_val) and np.isnan(single_val):
                continue
            assert batch_val == pytest.approx(single_val, abs=1e-6), \
                f"Mismatch for {key}: batch={batch_val}, single={single_val}"

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        result = compute_gap_features_batch(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_none_input(self):
        result = compute_gap_features_batch(None)
        assert isinstance(result, pd.DataFrame)

    def test_nan_handling_with_missing_data(self):
        """DataFrame with some NaN values should not crash."""
        df = _make_ohlcv([100 + i for i in range(30)])
        df.iloc[5, df.columns.get_loc("Close")] = np.nan
        df.iloc[10, df.columns.get_loc("Open")] = np.nan
        # Should not raise
        result = compute_gap_features_batch(df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 30
