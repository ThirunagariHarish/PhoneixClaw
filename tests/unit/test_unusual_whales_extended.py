"""Unit tests for extended Unusual Whales client methods and feature computation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import numpy as np
import pytest

from shared.unusual_whales.client import UnusualWhalesClient
from shared.unusual_whales.models import (
    DarkPoolFlow,
    InstitutionalHolding,
    ShortInterest,
    VolSurface,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """Create a client with no Redis and dummy token."""
    return UnusualWhalesClient(api_token="test-token", redis_url=None, cache_ttl=1)


@pytest.fixture()
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def _run(loop, coro):
    return loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_dark_pool_flow_defaults(self):
        dp = DarkPoolFlow(ticker="AAPL")
        assert dp.total_volume == 0
        assert dp.dp_percentage is None

    def test_short_interest_defaults(self):
        si = ShortInterest(ticker="TSLA")
        assert si.short_interest is None
        assert si.shares_short == 0

    def test_vol_surface_defaults(self):
        vs = VolSurface(ticker="MSFT")
        assert vs.skew_25d is None
        assert vs.term_structure == {}

    def test_institutional_holding_defaults(self):
        ih = InstitutionalHolding(ticker="NVDA")
        assert ih.num_holders == 0
        assert ih.top_holders == []


# ---------------------------------------------------------------------------
# Client endpoint tests (mocked HTTP)
# ---------------------------------------------------------------------------

class TestDarkPool:
    def test_returns_dark_pool_flow(self, client, event_loop):
        mock_resp = {
            "data": {
                "total_volume": 5_000_000,
                "total_notional": 750_000_000.0,
                "dp_percentage": 38.5,
                "block_trades": 142,
                "avg_trade_size": 35211.0,
                "sentiment": "bullish",
            }
        }
        client._request = AsyncMock(return_value=mock_resp)
        result = _run(event_loop, client.get_dark_pool("AAPL"))

        assert isinstance(result, DarkPoolFlow)
        assert result.ticker == "AAPL"
        assert result.total_volume == 5_000_000
        assert result.dp_percentage == 38.5
        assert result.sentiment == "bullish"

    def test_returns_empty_on_error(self, client, event_loop):
        client._request = AsyncMock(side_effect=Exception("API error"))
        result = _run(event_loop, client.get_dark_pool("AAPL"))
        assert isinstance(result, DarkPoolFlow)
        assert result.dp_percentage is None


class TestCongressionalTrades:
    def test_returns_trades_list(self, client, event_loop):
        mock_resp = {
            "data": [
                {
                    "transaction_type": "Purchase",
                    "amount": "$1,001 - $15,000",
                    "representative": "Nancy Pelosi",
                    "disclosure_date": "2024-03-15",
                    "transaction_date": "2024-03-10",
                },
                {
                    "transaction_type": "Sale",
                    "amount": "$15,001 - $50,000",
                    "representative": "Dan Crenshaw",
                    "disclosure_date": "2024-03-12",
                    "transaction_date": "2024-03-08",
                },
            ]
        }
        client._request = AsyncMock(return_value=mock_resp)
        result = _run(event_loop, client.get_congressional_trades("AAPL"))

        assert len(result) == 2
        assert result[0].transaction_type == "Purchase"
        assert result[1].representative == "Dan Crenshaw"

    def test_returns_empty_on_error(self, client, event_loop):
        client._request = AsyncMock(side_effect=Exception("fail"))
        result = _run(event_loop, client.get_congressional_trades("AAPL"))
        assert result == []


class TestInsiderTrades:
    def test_returns_trades(self, client, event_loop):
        mock_resp = {
            "data": [
                {
                    "insider_name": "Tim Cook",
                    "title": "CEO",
                    "transaction_type": "Sell",
                    "shares": 50000,
                    "value": 8_750_000.0,
                    "filing_date": "2024-02-15",
                }
            ]
        }
        client._request = AsyncMock(return_value=mock_resp)
        result = _run(event_loop, client.get_insider_trades("AAPL"))
        assert len(result) == 1
        assert result[0].shares == 50000

    def test_empty_on_error(self, client, event_loop):
        client._request = AsyncMock(side_effect=Exception("nope"))
        result = _run(event_loop, client.get_insider_trades("AAPL"))
        assert result == []


class TestShortInterest:
    def test_returns_short_interest(self, client, event_loop):
        mock_resp = {
            "data": {
                "short_interest": 0.045,
                "shares_short": 12_000_000,
                "days_to_cover": 2.3,
                "short_percent_of_float": 4.5,
                "change_pct": -0.8,
            }
        }
        client._request = AsyncMock(return_value=mock_resp)
        result = _run(event_loop, client.get_short_interest("GME"))
        assert isinstance(result, ShortInterest)
        assert result.days_to_cover == 2.3
        assert result.short_percent_of_float == 4.5

    def test_empty_on_error(self, client, event_loop):
        client._request = AsyncMock(side_effect=Exception("err"))
        result = _run(event_loop, client.get_short_interest("GME"))
        assert result.short_interest is None


class TestInstitutionalActivity:
    def test_returns_holding(self, client, event_loop):
        mock_resp = {
            "data": {
                "total_institutional_shares": 1_000_000_000,
                "institutional_ownership_pct": 72.5,
                "num_holders": 4500,
                "change_in_shares": 50_000_000,
                "top_holders": [
                    {"name": "Vanguard", "shares": 200_000_000},
                    {"name": "BlackRock", "shares": 180_000_000},
                ],
            }
        }
        client._request = AsyncMock(return_value=mock_resp)
        result = _run(event_loop, client.get_institutional_activity("AAPL"))
        assert isinstance(result, InstitutionalHolding)
        assert result.institutional_ownership_pct == 72.5
        assert result.num_holders == 4500

    def test_empty_on_error(self, client, event_loop):
        client._request = AsyncMock(side_effect=Exception("err"))
        result = _run(event_loop, client.get_institutional_activity("AAPL"))
        assert result.num_holders == 0


class TestVolatilitySurface:
    def test_returns_vol_surface(self, client, event_loop):
        mock_resp = {
            "data": {
                "skew_25d": -0.12,
                "term_structure": {"30d": 0.28, "60d": 0.26, "90d": 0.25},
                "atm_iv_30d": 0.28,
                "atm_iv_60d": 0.26,
                "atm_iv_90d": 0.25,
                "butterfly_25d": 0.03,
            }
        }
        client._request = AsyncMock(return_value=mock_resp)
        result = _run(event_loop, client.get_volatility_surface("AAPL"))
        assert isinstance(result, VolSurface)
        assert result.skew_25d == -0.12
        assert result.atm_iv_30d == 0.28

    def test_empty_on_error(self, client, event_loop):
        client._request = AsyncMock(side_effect=Exception("err"))
        result = _run(event_loop, client.get_volatility_surface("AAPL"))
        assert result.skew_25d is None


# ---------------------------------------------------------------------------
# get_all_extended_features
# ---------------------------------------------------------------------------

class TestGetAllExtendedFeatures:
    def test_returns_all_feature_keys(self, client, event_loop):
        """All feature keys should be present even when API returns real data."""
        # Mock all endpoints with reasonable data
        client.get_dark_pool = AsyncMock(return_value=DarkPoolFlow(
            ticker="AAPL", dp_percentage=38.5, block_trades=100,
            avg_trade_size=5000.0, sentiment="bullish",
        ))
        client.get_congressional_trades = AsyncMock(return_value=[])
        client.get_insider_trades = AsyncMock(return_value=[])
        client.get_short_interest = AsyncMock(return_value=ShortInterest(
            ticker="AAPL", short_percent_of_float=4.5, days_to_cover=2.3,
            short_interest=0.045, change_pct=-0.8,
        ))
        client.get_institutional_activity = AsyncMock(return_value=InstitutionalHolding(
            ticker="AAPL", institutional_ownership_pct=72.5, num_holders=4500,
            change_in_shares=50_000_000, total_institutional_shares=1_000_000_000,
        ))
        client.get_volatility_surface = AsyncMock(return_value=VolSurface(
            ticker="AAPL", skew_25d=-0.12, atm_iv_30d=0.28, atm_iv_60d=0.26,
            butterfly_25d=0.03,
        ))

        feats = _run(event_loop, client.get_all_extended_features("AAPL"))

        expected_keys = [
            "darkpool_volume_pct", "darkpool_block_count",
            "darkpool_avg_block_size", "darkpool_net_sentiment",
            "darkpool_lit_ratio",
            "congress_buy_count_30d", "congress_sell_count_30d",
            "congress_net_trades_30d", "congress_total_value_30d",
            "insider_uw_buy_count_90d", "insider_uw_sell_count_90d",
            "insider_uw_net_shares_90d", "insider_uw_buy_sell_ratio",
            "insider_uw_latest_days_ago",
            "short_interest_pct", "short_interest_days_to_cover",
            "short_utilization", "short_interest_change_30d",
            "institutional_ownership_pct", "institutional_count",
            "institutional_net_change_qtr", "top10_concentration",
            "iv_term_structure_slope", "iv_skew_25d",
            "vol_surface_atm_30d", "vol_surface_atm_60d",
            "vol_smile_curvature", "iv_term_spread_30_60",
        ]
        for key in expected_keys:
            assert key in feats, f"Missing feature key: {key}"

    def test_all_nan_on_total_failure(self, client, event_loop):
        """When every endpoint fails, all features should be NaN."""
        client.get_dark_pool = AsyncMock(side_effect=Exception("fail"))
        client.get_congressional_trades = AsyncMock(side_effect=Exception("fail"))
        client.get_insider_trades = AsyncMock(side_effect=Exception("fail"))
        client.get_short_interest = AsyncMock(side_effect=Exception("fail"))
        client.get_institutional_activity = AsyncMock(side_effect=Exception("fail"))
        client.get_volatility_surface = AsyncMock(side_effect=Exception("fail"))

        feats = _run(event_loop, client.get_all_extended_features("AAPL"))

        assert isinstance(feats, dict)
        assert len(feats) > 0
        for key, val in feats.items():
            assert isinstance(val, float), f"{key} is not a float: {type(val)}"
            assert np.isnan(val), f"{key} should be NaN but is {val}"

    def test_partial_failure(self, client, event_loop):
        """When some endpoints fail, those features are NaN; others are valid."""
        client.get_dark_pool = AsyncMock(return_value=DarkPoolFlow(
            ticker="AAPL", dp_percentage=38.5, block_trades=100,
            avg_trade_size=5000.0, sentiment="bullish",
        ))
        # Everything else fails
        client.get_congressional_trades = AsyncMock(side_effect=Exception("fail"))
        client.get_insider_trades = AsyncMock(side_effect=Exception("fail"))
        client.get_short_interest = AsyncMock(side_effect=Exception("fail"))
        client.get_institutional_activity = AsyncMock(side_effect=Exception("fail"))
        client.get_volatility_surface = AsyncMock(side_effect=Exception("fail"))

        feats = _run(event_loop, client.get_all_extended_features("AAPL"))

        # Dark pool features should be valid
        assert feats["darkpool_volume_pct"] == 38.5
        assert feats["darkpool_block_count"] == 100.0
        assert feats["darkpool_net_sentiment"] == 1.0  # bullish

        # Congressional features should be NaN
        assert np.isnan(feats["congress_buy_count_30d"])

    def test_cache_behavior(self, client, event_loop):
        """Second call should use cache and not hit the API again."""
        mock_resp = {
            "data": {
                "total_volume": 5_000_000,
                "dp_percentage": 38.5,
                "block_trades": 142,
                "avg_trade_size": 35211.0,
                "sentiment": "bullish",
            }
        }
        client._request = AsyncMock(return_value=mock_resp)

        # First call
        result1 = _run(event_loop, client.get_dark_pool("AAPL"))
        # Second call -- should come from cache
        result2 = _run(event_loop, client.get_dark_pool("AAPL"))

        assert result1.dp_percentage == result2.dp_percentage
        # _request should have been called only once (second hits cache)
        assert client._request.call_count == 1
