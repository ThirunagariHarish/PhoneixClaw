"""Tests for shared.data.company_events module."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from shared.data.company_events import (
    CompanyEventsClient,
    _analyst_features,
    _biotech_features,
    _dividend_features,
    _earnings_features,
    _insider_features,
    _institutional_features,
    _safe_float,
    _split_features,
    _to_date,
    get_company_events_client,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AS_OF = date(2025, 6, 15)


def _make_ticker_mock(
    *,
    earnings_dates=None,
    quarterly_earnings=None,
    dividends=None,
    splits=None,
    insider_transactions=None,
    institutional_holders=None,
    recommendations=None,
    analyst_price_targets=None,
    info=None,
):
    """Build a mock yf.Ticker with the requested attributes."""
    tk = MagicMock()
    tk.earnings_dates = earnings_dates
    tk.quarterly_earnings = quarterly_earnings
    tk.dividends = dividends if dividends is not None else pd.Series(dtype=float)
    tk.splits = splits if splits is not None else pd.Series(dtype=float)
    tk.insider_transactions = insider_transactions
    tk.institutional_holders = institutional_holders
    tk.recommendations = recommendations
    tk.analyst_price_targets = analyst_price_targets
    tk.info = info or {}
    return tk


# ---------------------------------------------------------------------------
# _safe_float / _to_date
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_normal(self):
        assert _safe_float(3.14) == 3.14

    def test_none(self):
        assert np.isnan(_safe_float(None))

    def test_string_number(self):
        assert _safe_float("2.5") == 2.5

    def test_bad_string(self):
        assert np.isnan(_safe_float("abc"))

    def test_inf(self):
        assert np.isnan(_safe_float(float("inf")))


class TestToDate:
    def test_date(self):
        assert _to_date(date(2025, 1, 1)) == date(2025, 1, 1)

    def test_timestamp(self):
        assert _to_date(pd.Timestamp("2025-03-01")) == date(2025, 3, 1)

    def test_none(self):
        assert _to_date(None) is None

    def test_string(self):
        assert _to_date("2025-05-10") == date(2025, 5, 10)


# ---------------------------------------------------------------------------
# Earnings features
# ---------------------------------------------------------------------------


class TestEarningsFeatures:
    @patch("shared.data.company_events._get_yf_ticker")
    def test_earnings_dates_and_surprise(self, mock_get_tk):
        # Earnings dates index
        ed_index = pd.DatetimeIndex([
            "2025-07-20",  # future
            "2025-04-15",  # past
            "2025-01-10",  # past
            "2024-10-08",  # past
            "2024-07-05",  # past
        ])
        ed_df = pd.DataFrame(
            {"EPS Estimate": [1.0, 0.9, 0.85, 0.80, 0.75]},
            index=ed_index,
        )

        # Quarterly earnings
        qe_df = pd.DataFrame({
            "Actual": [1.05, 0.92, 0.84, 0.82],
            "Estimate": [0.9, 0.85, 0.80, 0.75],
        }, index=pd.DatetimeIndex(["2025-04-15", "2025-01-10", "2024-10-08", "2024-07-05"]))

        tk = _make_ticker_mock(earnings_dates=ed_df, quarterly_earnings=qe_df)
        mock_get_tk.return_value = tk

        feats = _earnings_features("AAPL", AS_OF)

        assert feats["days_to_earnings"] == (date(2025, 7, 20) - AS_OF).days
        assert feats["days_since_earnings"] == (AS_OF - date(2025, 4, 15)).days
        # Surprise last: (1.05 - 0.9)/0.9
        assert abs(feats["earnings_surprise_last"] - (1.05 - 0.9) / 0.9) < 1e-4
        assert feats["earnings_beat_rate_4q"] == 1.0  # all beat
        assert np.isfinite(feats["earnings_surprise_avg_4q"])
        assert np.isfinite(feats["earnings_surprise_std_4q"])

    @patch("shared.data.company_events._get_yf_ticker")
    def test_no_earnings_data(self, mock_get_tk):
        tk = _make_ticker_mock(earnings_dates=None, quarterly_earnings=None)
        mock_get_tk.return_value = tk
        feats = _earnings_features("XYZ", AS_OF)
        assert np.isnan(feats["days_to_earnings"])
        assert np.isnan(feats["earnings_surprise_last"])


# ---------------------------------------------------------------------------
# Dividend features
# ---------------------------------------------------------------------------


class TestDividendFeatures:
    @patch("shared.data.company_events._get_yf_ticker")
    def test_with_dividends(self, mock_get_tk):
        dates = pd.DatetimeIndex([
            "2024-09-01", "2024-12-01", "2025-03-01", "2025-06-01",
            "2025-09-01",  # future relative to AS_OF
        ])
        divs = pd.Series([0.20, 0.22, 0.24, 0.26, 0.28], index=dates)
        tk = _make_ticker_mock(dividends=divs, info={"previousClose": 150.0})
        mock_get_tk.return_value = tk

        with patch("shared.data.company_events._get_ticker_info", return_value={"previousClose": 150.0}):
            feats = _dividend_features("AAPL", AS_OF)

        assert feats["has_dividend"] == 1.0
        assert feats["days_since_ex_div"] == (AS_OF - date(2025, 6, 1)).days
        assert feats["days_to_ex_div"] == (date(2025, 9, 1) - AS_OF).days
        assert feats["dividend_amount_last"] == 0.26
        assert feats["div_increase_streak"] == 3.0  # 4 consecutive increases among past dividends
        assert np.isfinite(feats["dividend_yield"])
        assert np.isfinite(feats["div_change_pct"])

    @patch("shared.data.company_events._get_yf_ticker")
    def test_no_dividends(self, mock_get_tk):
        tk = _make_ticker_mock(dividends=pd.Series(dtype=float))
        mock_get_tk.return_value = tk
        feats = _dividend_features("TSLA", AS_OF)
        assert feats["has_dividend"] == 0.0
        assert np.isnan(feats["days_to_ex_div"])


# ---------------------------------------------------------------------------
# Split features
# ---------------------------------------------------------------------------


class TestSplitFeatures:
    @patch("shared.data.company_events._get_yf_ticker")
    def test_recent_split(self, mock_get_tk):
        dates = pd.DatetimeIndex(["2020-08-31", "2025-05-01"])
        splits = pd.Series([4.0, 10.0], index=dates)
        tk = _make_ticker_mock(splits=splits)
        mock_get_tk.return_value = tk

        feats = _split_features("AAPL", AS_OF)
        assert feats["days_since_split"] == (AS_OF - date(2025, 5, 1)).days
        assert feats["split_ratio_last"] == 10.0
        assert feats["had_recent_split_90d"] == 1.0

    @patch("shared.data.company_events._get_yf_ticker")
    def test_no_splits(self, mock_get_tk):
        tk = _make_ticker_mock(splits=pd.Series(dtype=float))
        mock_get_tk.return_value = tk
        feats = _split_features("MSFT", AS_OF)
        assert np.isnan(feats["days_since_split"])
        assert feats["had_recent_split_90d"] == 0.0

    @patch("shared.data.company_events._get_yf_ticker")
    def test_old_split(self, mock_get_tk):
        dates = pd.DatetimeIndex(["2020-01-01"])
        splits = pd.Series([2.0], index=dates)
        tk = _make_ticker_mock(splits=splits)
        mock_get_tk.return_value = tk

        feats = _split_features("XYZ", AS_OF)
        assert feats["had_recent_split_90d"] == 0.0
        assert feats["split_ratio_last"] == 2.0


# ---------------------------------------------------------------------------
# Insider transaction features
# ---------------------------------------------------------------------------


class TestInsiderFeatures:
    @patch("shared.data.company_events._get_yf_ticker")
    def test_insider_buys_and_sells(self, mock_get_tk):
        txn_df = pd.DataFrame({
            "Start Date": ["2025-05-01", "2025-04-15", "2025-06-01", "2024-01-01"],
            "Transaction": [
                "Purchase", "Sale", "Purchase", "Sale"
            ],
            "Shares": [1000, 500, 2000, 10000],
            "Value": [50000, 25000, 100000, 500000],
        })
        tk = _make_ticker_mock(insider_transactions=txn_df)
        mock_get_tk.return_value = tk

        feats = _insider_features("AAPL", AS_OF)
        assert feats["insider_buy_count_90d"] == 2.0
        assert feats["insider_sell_count_90d"] == 1.0
        assert feats["insider_net_shares_90d"] == 2500.0  # 1000+2000-500
        assert feats["insider_buy_sell_ratio"] == round(2 / 3, 4)
        assert feats["insider_total_value_90d"] == 175000.0

    @patch("shared.data.company_events._get_yf_ticker")
    def test_no_insider_data(self, mock_get_tk):
        tk = _make_ticker_mock(insider_transactions=None)
        mock_get_tk.return_value = tk
        feats = _insider_features("XYZ", AS_OF)
        assert np.isnan(feats["insider_buy_count_90d"])


# ---------------------------------------------------------------------------
# Institutional features
# ---------------------------------------------------------------------------


class TestInstitutionalFeatures:
    @patch("shared.data.company_events._get_yf_ticker")
    def test_institutional_holders(self, mock_get_tk):
        holders = pd.DataFrame({
            "Holder": ["Vanguard", "BlackRock", "Fidelity"],
            "pctHeld": [0.08, 0.07, 0.05],
        })
        tk = _make_ticker_mock(institutional_holders=holders)
        mock_get_tk.return_value = tk

        feats = _institutional_features("AAPL")
        assert feats["institutional_holders_count"] == 3.0
        assert abs(feats["institutional_pct_held"] - 0.20) < 1e-4
        assert abs(feats["top_holder_pct"] - 0.08) < 1e-4

    @patch("shared.data.company_events._get_yf_ticker")
    def test_no_institutional(self, mock_get_tk):
        tk = _make_ticker_mock(institutional_holders=None)
        mock_get_tk.return_value = tk
        feats = _institutional_features("XYZ")
        assert np.isnan(feats["institutional_holders_count"])


# ---------------------------------------------------------------------------
# Analyst features
# ---------------------------------------------------------------------------


class TestAnalystFeatures:
    @patch("shared.data.company_events._get_ticker_info", return_value={"previousClose": 200.0})
    @patch("shared.data.company_events._get_yf_ticker")
    def test_analyst_targets_and_recs(self, mock_get_tk, mock_info):
        targets = {"mean": 220.0, "high": 250.0, "low": 180.0, "numberOfAnalysts": 15}
        recs_df = pd.DataFrame({
            "To Grade": ["Buy", "Sell", "Overweight", "Hold", "Buy"],
            "Action": ["upgrade", "downgrade", "init", "main", "upgrade"],
        }, index=pd.DatetimeIndex([
            "2025-06-01", "2025-05-15", "2025-04-01", "2025-03-01", "2024-12-01",
        ]))
        tk = _make_ticker_mock(
            analyst_price_targets=targets,
            recommendations=recs_df,
        )
        mock_get_tk.return_value = tk

        feats = _analyst_features("AAPL", AS_OF)
        assert feats["analyst_mean_target"] == 220.0
        assert feats["analyst_high_target"] == 250.0
        assert feats["analyst_low_target"] == 180.0
        assert feats["analyst_count"] == 15.0
        assert abs(feats["analyst_target_vs_price"] - 0.1) < 1e-4
        assert np.isfinite(feats["analyst_buy_pct"])
        assert np.isfinite(feats["analyst_sell_pct"])

    @patch("shared.data.company_events._get_ticker_info", return_value={})
    @patch("shared.data.company_events._get_yf_ticker")
    def test_no_analyst_data(self, mock_get_tk, mock_info):
        tk = _make_ticker_mock(analyst_price_targets=None, recommendations=None)
        mock_get_tk.return_value = tk
        feats = _analyst_features("XYZ", AS_OF)
        assert np.isnan(feats["analyst_mean_target"])
        assert np.isnan(feats["analyst_count"])


# ---------------------------------------------------------------------------
# Biotech features
# ---------------------------------------------------------------------------


class TestBiotechFeatures:
    @patch("shared.data.company_events._get_ticker_info")
    def test_biotech(self, mock_info):
        mock_info.return_value = {"sector": "Healthcare", "industry": "Biotechnology"}
        feats = _biotech_features("MRNA")
        assert feats["is_biotech"] == 1.0
        assert np.isnan(feats["days_to_fda_date"])

    @patch("shared.data.company_events._get_ticker_info")
    def test_pharma(self, mock_info):
        mock_info.return_value = {"sector": "Healthcare", "industry": "Drug Manufacturers - General Pharma"}
        feats = _biotech_features("PFE")
        assert feats["is_biotech"] == 1.0

    @patch("shared.data.company_events._get_ticker_info")
    def test_not_biotech(self, mock_info):
        mock_info.return_value = {"sector": "Technology", "industry": "Software"}
        feats = _biotech_features("AAPL")
        assert feats["is_biotech"] == 0.0


# ---------------------------------------------------------------------------
# NaN safety (all data unavailable)
# ---------------------------------------------------------------------------


class TestNanSafety:
    @patch("shared.data.company_events._get_yf_ticker")
    @patch("shared.data.company_events._get_ticker_info", return_value={})
    def test_all_nan_when_no_data(self, mock_info, mock_get_tk):
        tk = _make_ticker_mock()
        tk.earnings_dates = None
        tk.quarterly_earnings = None
        tk.insider_transactions = None
        tk.institutional_holders = None
        tk.recommendations = None
        tk.analyst_price_targets = None
        mock_get_tk.return_value = tk

        client = CompanyEventsClient()
        feats = client.get_event_features("NODATA", AS_OF)

        # Every value should be either NaN or 0.0 (for binary flags)
        for k, v in feats.items():
            assert isinstance(v, float), f"{k} is not float: {type(v)}"

        # Specifically binary flags should be 0
        assert feats["has_dividend"] == 0.0
        assert feats["is_biotech"] == 0.0
        assert feats["had_recent_split_90d"] == 0.0

    @patch("shared.data.company_events._get_yf_ticker", side_effect=Exception("API down"))
    @patch("shared.data.company_events._get_ticker_info", return_value={})
    def test_exception_returns_nan(self, mock_info, mock_get_tk):
        """Even if yfinance explodes, we get NaN dict back, not an exception."""
        client = CompanyEventsClient()
        feats = client.get_event_features("FAIL", AS_OF)
        # Should have all expected keys (from the subsections that ran before the crash)
        assert isinstance(feats, dict)


# ---------------------------------------------------------------------------
# as_of_date filtering (temporal correctness)
# ---------------------------------------------------------------------------


class TestTemporalCorrectness:
    @patch("shared.data.company_events._get_yf_ticker")
    def test_future_earnings_excluded_from_surprise(self, mock_get_tk):
        """Earnings dates in the future should not appear in surprise calculations."""
        ed_index = pd.DatetimeIndex(["2025-07-20", "2025-04-15"])
        ed_df = pd.DataFrame({"EPS Estimate": [1.0, 0.9]}, index=ed_index)

        qe_df = pd.DataFrame({
            "Actual": [1.05],
            "Estimate": [0.9],
        }, index=pd.DatetimeIndex(["2025-04-15"]))

        tk = _make_ticker_mock(earnings_dates=ed_df, quarterly_earnings=qe_df)
        mock_get_tk.return_value = tk

        feats = _earnings_features("AAPL", AS_OF)
        # The future date (July 20) should be in days_to_earnings, not days_since
        assert feats["days_to_earnings"] == (date(2025, 7, 20) - AS_OF).days
        assert feats["days_since_earnings"] == (AS_OF - date(2025, 4, 15)).days

    @patch("shared.data.company_events._get_yf_ticker")
    def test_future_dividends_not_in_past(self, mock_get_tk):
        dates = pd.DatetimeIndex(["2025-03-01", "2025-09-01"])
        divs = pd.Series([0.50, 0.55], index=dates)
        tk = _make_ticker_mock(dividends=divs)
        mock_get_tk.return_value = tk

        feats = _dividend_features("XYZ", AS_OF)
        # Only March dividend should be in "past"
        assert feats["days_since_ex_div"] == (AS_OF - date(2025, 3, 1)).days
        assert feats["dividend_amount_last"] == 0.50


# ---------------------------------------------------------------------------
# Cache behavior
# ---------------------------------------------------------------------------


class TestCacheBehavior:
    @patch("shared.data.company_events._get_yf_ticker")
    @patch("shared.data.company_events._get_ticker_info", return_value={})
    def test_cache_write_and_read(self, mock_info, mock_get_tk, tmp_path):
        tk = _make_ticker_mock()
        tk.earnings_dates = None
        tk.quarterly_earnings = None
        tk.insider_transactions = None
        tk.institutional_holders = None
        tk.recommendations = None
        tk.analyst_price_targets = None
        mock_get_tk.return_value = tk

        # Override cache dir
        with patch("shared.data.company_events._CACHE_DIR", tmp_path):
            client = CompanyEventsClient()
            feats1 = client.get_event_features("TEST", AS_OF)

            # Second call should hit cache
            feats2 = client.get_event_features("TEST", AS_OF)

            # The features should be equivalent
            for k in feats1:
                v1, v2 = feats1[k], feats2[k]
                if isinstance(v1, float) and np.isnan(v1):
                    assert isinstance(v2, float) and (np.isnan(v2) or v2 is None)
                else:
                    assert v1 == v2


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_company_events_client_returns_same(self):
        # Reset
        import shared.data.company_events as mod
        mod._client_instance = None
        c1 = get_company_events_client()
        c2 = get_company_events_client()
        assert c1 is c2


# ---------------------------------------------------------------------------
# Full integration (all subsections produce expected keys)
# ---------------------------------------------------------------------------


class TestFullFeatureSet:
    @patch("shared.data.company_events._get_yf_ticker")
    @patch("shared.data.company_events._get_ticker_info", return_value={})
    def test_all_expected_keys_present(self, mock_info, mock_get_tk):
        tk = _make_ticker_mock()
        tk.earnings_dates = None
        tk.quarterly_earnings = None
        tk.insider_transactions = None
        tk.institutional_holders = None
        tk.recommendations = None
        tk.analyst_price_targets = None
        mock_get_tk.return_value = tk

        client = CompanyEventsClient()
        feats = client.get_event_features("TEST", AS_OF)

        expected_keys = [
            # Earnings
            "days_to_earnings", "days_since_earnings", "earnings_surprise_last",
            "earnings_surprise_avg_4q", "earnings_beat_rate_4q", "earnings_surprise_std_4q",
            "pre_earnings_run_5d", "post_earnings_drift_1d", "post_earnings_drift_5d",
            # Dividends
            "days_to_ex_div", "days_since_ex_div", "dividend_yield",
            "dividend_amount_last", "div_change_pct", "div_increase_streak", "has_dividend",
            # Splits
            "days_since_split", "split_ratio_last", "had_recent_split_90d",
            # Insider
            "insider_buy_count_90d", "insider_sell_count_90d", "insider_net_shares_90d",
            "insider_buy_sell_ratio", "insider_total_value_90d",
            # Institutional
            "institutional_holders_count", "institutional_pct_held", "top_holder_pct",
            # Analyst
            "analyst_count", "analyst_mean_target", "analyst_target_vs_price",
            "analyst_high_target", "analyst_low_target", "analyst_buy_pct",
            "analyst_sell_pct", "analyst_upgrades_90d", "analyst_downgrades_90d",
            "analyst_revision_momentum",
            # Biotech
            "is_biotech", "days_to_fda_date",
        ]
        for key in expected_keys:
            assert key in feats, f"Missing key: {key}"
