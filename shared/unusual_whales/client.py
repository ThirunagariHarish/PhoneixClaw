"""
Async HTTP client for the Unusual Whales API.

Handles authentication, rate limiting, caching, and response parsing.
"""

import logging
import os
from datetime import datetime, timezone

import httpx

from .cache import UWCache
from .models import (
    CongressionalTrade,
    DarkPoolFlow,
    GexData,
    InsiderTrade,
    InstitutionalHolding,
    MarketTide,
    OptionChain,
    OptionContract,
    OptionsFlow,
    ShortInterest,
    VolSurface,
)

logger = logging.getLogger(__name__)

UW_BASE_URL = os.getenv("UNUSUAL_WHALES_BASE_URL", "https://api.unusualwhales.com")
UW_API_TOKEN = os.getenv("UNUSUAL_WHALES_API_TOKEN", "")
REDIS_URL = os.getenv("REDIS_URL", None)
CACHE_TTL = int(os.getenv("UW_CACHE_TTL", "300"))


class UnusualWhalesClient:
    """Client for interacting with the Unusual Whales API."""

    def __init__(
        self,
        api_token: str | None = None,
        base_url: str = UW_BASE_URL,
        cache_ttl: int = CACHE_TTL,
        redis_url: str | None = REDIS_URL,
    ):
        self.api_token = api_token or UW_API_TOKEN
        self.base_url = base_url.rstrip("/")
        self.cache = UWCache(redis_url=redis_url, default_ttl=cache_ttl)
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_token}",
                    "Accept": "application/json",
                },
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(self, method: str, path: str, params: dict | None = None) -> dict:
        client = await self._get_client()
        resp = await client.request(method, path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_option_chain(self, ticker: str, expiration: str | None = None) -> OptionChain:
        """Fetch option chain for a ticker."""
        cache_key = f"chain:{ticker}:{expiration or 'all'}"
        cached = await self.cache.get(cache_key)
        if cached:
            return OptionChain(**cached)

        params: dict = {}
        if expiration:
            params["expiration"] = expiration

        try:
            data = await self._request("GET", f"/api/stock/{ticker}/option-chain", params=params)
            contracts = []
            for item in data.get("data", []):
                contracts.append(OptionContract(
                    ticker=ticker,
                    strike=float(item.get("strike", 0)),
                    option_type="CALL" if item.get("option_type", "").upper().startswith("C") else "PUT",
                    expiration=item.get("expiration", ""),
                    bid=item.get("bid"),
                    ask=item.get("ask"),
                    mid=item.get("mid"),
                    volume=item.get("volume", 0),
                    open_interest=item.get("open_interest", 0),
                    implied_volatility=item.get("implied_volatility"),
                    delta=item.get("delta"),
                    gamma=item.get("gamma"),
                    theta=item.get("theta"),
                    vega=item.get("vega"),
                    iv_rank=item.get("iv_rank"),
                ))
            chain = OptionChain(
                ticker=ticker,
                contracts=contracts,
                updated_at=datetime.now(timezone.utc),
            )
            await self.cache.set(cache_key, chain.model_dump())
            return chain
        except Exception as e:
            logger.error("Failed to fetch option chain for %s: %s", ticker, e)
            return OptionChain(ticker=ticker)

    async def get_options_flow(self, ticker: str | None = None, limit: int = 50) -> list[OptionsFlow]:
        """Fetch recent options flow data."""
        cache_key = f"flow:{ticker or 'all'}:{limit}"
        cached = await self.cache.get(cache_key)
        if cached:
            return [OptionsFlow(**f) for f in cached.get("flows", [])]

        params: dict = {"limit": limit}
        path = f"/api/stock/{ticker}/options-flow" if ticker else "/api/options-flow"

        try:
            data = await self._request("GET", path, params=params)
            flows = []
            for item in data.get("data", []):
                flows.append(OptionsFlow(
                    ticker=item.get("ticker", ticker or ""),
                    strike=float(item.get("strike", 0)),
                    option_type="CALL" if item.get("put_call", "").upper().startswith("C") else "PUT",
                    expiration=item.get("expiration", ""),
                    sentiment=item.get("sentiment"),
                    volume=item.get("volume", 0),
                    open_interest=item.get("open_interest", 0),
                    premium=item.get("premium"),
                    trade_type=item.get("trade_type"),
                    timestamp=item.get("executed_at"),
                ))
            await self.cache.set(cache_key, {"flows": [f.model_dump() for f in flows]})
            return flows
        except Exception as e:
            logger.error("Failed to fetch options flow: %s", e)
            return []

    async def get_gex(self, ticker: str) -> GexData:
        """Fetch GEX (Gamma Exposure) data."""
        cache_key = f"gex:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return GexData(**cached)

        try:
            data = await self._request("GET", f"/api/stock/{ticker}/gamma-exposure")
            gex_info = data.get("data", {})
            gex = GexData(
                ticker=ticker,
                total_gex=gex_info.get("total_gex"),
                call_gex=gex_info.get("call_gex"),
                put_gex=gex_info.get("put_gex"),
                gex_by_strike=gex_info.get("gex_by_strike", {}),
                zero_gamma_level=gex_info.get("zero_gamma_level"),
            )
            await self.cache.set(cache_key, gex.model_dump())
            return gex
        except Exception as e:
            logger.error("Failed to fetch GEX for %s: %s", ticker, e)
            return GexData(ticker=ticker)

    async def get_market_tide(self) -> MarketTide:
        """Fetch overall market tide / sentiment data."""
        cache_key = "market_tide"
        cached = await self.cache.get(cache_key)
        if cached:
            return MarketTide(**cached)

        try:
            data = await self._request("GET", "/api/market/tide")
            tide_data = data.get("data", {})
            tide = MarketTide(
                net_premium=tide_data.get("net_premium"),
                call_premium=tide_data.get("call_premium"),
                put_premium=tide_data.get("put_premium"),
                call_volume=tide_data.get("call_volume", 0),
                put_volume=tide_data.get("put_volume", 0),
                put_call_ratio=tide_data.get("put_call_ratio"),
                timestamp=datetime.now(timezone.utc),
            )
            await self.cache.set(cache_key, tide.model_dump())
            return tide
        except Exception as e:
            logger.error("Failed to fetch market tide: %s", e)
            return MarketTide()

    # ── Extended endpoints for feature engineering expansion ──────────

    async def get_dark_pool(self, ticker: str) -> DarkPoolFlow:
        """Fetch dark pool activity for *ticker*."""
        cache_key = f"darkpool:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return DarkPoolFlow(**cached)

        try:
            data = await self._request("GET", f"/api/stock/{ticker}/dark-pool")
            info = data.get("data", {}) if isinstance(data, dict) else {}
            dp = DarkPoolFlow(
                ticker=ticker,
                total_volume=int(info.get("total_volume", 0)),
                total_notional=float(info.get("total_notional", 0.0)),
                dp_percentage=info.get("dp_percentage"),
                block_trades=int(info.get("block_trades", 0)),
                avg_trade_size=info.get("avg_trade_size"),
                sentiment=info.get("sentiment"),
            )
            await self.cache.set(cache_key, dp.model_dump())
            return dp
        except Exception as e:
            logger.error("Failed to fetch dark pool for %s: %s", ticker, e)
            return DarkPoolFlow(ticker=ticker)

    async def get_congressional_trades(self, ticker: str) -> list[CongressionalTrade]:
        """Fetch congressional trading activity for *ticker*."""
        cache_key = f"congress:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return [CongressionalTrade(**t) for t in cached.get("trades", [])]

        try:
            data = await self._request("GET", f"/api/stock/{ticker}/congress")
            trades = []
            for item in data.get("data", []):
                trades.append(CongressionalTrade(
                    ticker=ticker,
                    transaction_type=item.get("transaction_type", ""),
                    amount_range=item.get("amount", ""),
                    representative=item.get("representative", ""),
                    disclosure_date=item.get("disclosure_date", ""),
                    transaction_date=item.get("transaction_date", ""),
                ))
            await self.cache.set(cache_key, {"trades": [t.model_dump() for t in trades]})
            return trades
        except Exception as e:
            logger.error("Failed to fetch congressional trades for %s: %s", ticker, e)
            return []

    async def get_insider_trades(self, ticker: str) -> list[InsiderTrade]:
        """Fetch insider trading activity for *ticker*."""
        cache_key = f"insider:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return [InsiderTrade(**t) for t in cached.get("trades", [])]

        try:
            data = await self._request("GET", f"/api/stock/{ticker}/insider-trades")
            trades = []
            for item in data.get("data", []):
                trades.append(InsiderTrade(
                    ticker=ticker,
                    insider_name=item.get("insider_name", ""),
                    title=item.get("title", ""),
                    transaction_type=item.get("transaction_type", ""),
                    shares=int(item.get("shares", 0)),
                    value=float(item.get("value", 0.0)),
                    filing_date=item.get("filing_date", ""),
                ))
            await self.cache.set(cache_key, {"trades": [t.model_dump() for t in trades]})
            return trades
        except Exception as e:
            logger.error("Failed to fetch insider trades for %s: %s", ticker, e)
            return []

    async def get_short_interest(self, ticker: str) -> ShortInterest:
        """Fetch short interest data for *ticker*."""
        cache_key = f"si:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return ShortInterest(**cached)

        try:
            data = await self._request("GET", f"/api/stock/{ticker}/short-interest")
            info = data.get("data", {}) if isinstance(data, dict) else {}
            si = ShortInterest(
                ticker=ticker,
                short_interest=info.get("short_interest"),
                shares_short=int(info.get("shares_short", 0)),
                days_to_cover=info.get("days_to_cover"),
                short_percent_of_float=info.get("short_percent_of_float"),
                change_pct=info.get("change_pct"),
            )
            await self.cache.set(cache_key, si.model_dump())
            return si
        except Exception as e:
            logger.error("Failed to fetch short interest for %s: %s", ticker, e)
            return ShortInterest(ticker=ticker)

    async def get_institutional_activity(self, ticker: str) -> InstitutionalHolding:
        """Fetch institutional holdings for *ticker*."""
        cache_key = f"inst:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return InstitutionalHolding(**cached)

        try:
            data = await self._request("GET", f"/api/stock/{ticker}/institutional")
            info = data.get("data", {}) if isinstance(data, dict) else {}
            holding = InstitutionalHolding(
                ticker=ticker,
                total_institutional_shares=int(info.get("total_institutional_shares", 0)),
                institutional_ownership_pct=info.get("institutional_ownership_pct"),
                num_holders=int(info.get("num_holders", 0)),
                change_in_shares=int(info.get("change_in_shares", 0)),
                top_holders=info.get("top_holders", []),
            )
            await self.cache.set(cache_key, holding.model_dump())
            return holding
        except Exception as e:
            logger.error("Failed to fetch institutional data for %s: %s", ticker, e)
            return InstitutionalHolding(ticker=ticker)

    async def get_volatility_surface(self, ticker: str) -> VolSurface:
        """Fetch volatility surface data for *ticker*."""
        cache_key = f"volsurf:{ticker}"
        cached = await self.cache.get(cache_key)
        if cached:
            return VolSurface(**cached)

        try:
            data = await self._request("GET", f"/api/stock/{ticker}/volatility-surface")
            info = data.get("data", {}) if isinstance(data, dict) else {}
            vs = VolSurface(
                ticker=ticker,
                skew_25d=info.get("skew_25d"),
                term_structure=info.get("term_structure", {}),
                atm_iv_30d=info.get("atm_iv_30d"),
                atm_iv_60d=info.get("atm_iv_60d"),
                atm_iv_90d=info.get("atm_iv_90d"),
                butterfly_25d=info.get("butterfly_25d"),
            )
            await self.cache.set(cache_key, vs.model_dump())
            return vs
        except Exception as e:
            logger.error("Failed to fetch vol surface for %s: %s", ticker, e)
            return VolSurface(ticker=ticker)

    async def get_all_extended_features(self, ticker: str,
                                        as_of_date: "object | None" = None) -> dict[str, float]:
        """Fetch all extended UW endpoints and compute features as a flat dict.

        Parameters
        ----------
        as_of_date : date | None
            Reference date for cutoff calculations.  Defaults to today.

        Every feature is guaranteed to be a float or np.nan -- never raises.
        """
        from datetime import date as _date_cls

        import numpy as _np

        _ref_date = as_of_date or _date_cls.today()

        features: dict[str, float] = {}

        def _sf(v, default=_np.nan):
            if v is None:
                return default
            try:
                f = float(v)
                return f if _np.isfinite(f) else default
            except (TypeError, ValueError):
                return default

        # Dark pool
        try:
            dp = await self.get_dark_pool(ticker)
            features["darkpool_volume_pct"] = _sf(dp.dp_percentage)
            features["darkpool_block_count"] = _sf(dp.block_trades, 0.0)
            features["darkpool_avg_block_size"] = _sf(dp.avg_trade_size)
            sent_map = {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}
            features["darkpool_net_sentiment"] = sent_map.get(
                (dp.sentiment or "").lower(), _np.nan
            )
            features["darkpool_lit_ratio"] = (
                _sf(1.0 - dp.dp_percentage / 100.0) if dp.dp_percentage is not None else _np.nan
            )
        except Exception:
            for k in ["darkpool_volume_pct", "darkpool_block_count",
                       "darkpool_avg_block_size", "darkpool_net_sentiment",
                       "darkpool_lit_ratio"]:
                features[k] = _np.nan

        # Congressional trades
        try:
            trades = await self.get_congressional_trades(ticker)
            from datetime import timedelta as _td

            cutoff_30d = _ref_date - _td(days=30)
            recent = [t for t in trades if t.transaction_date and
                      t.transaction_date >= cutoff_30d.isoformat()]
            buys = [t for t in recent if "purchase" in t.transaction_type.lower()]
            sells = [t for t in recent if "sale" in t.transaction_type.lower()]
            features["congress_buy_count_30d"] = float(len(buys))
            features["congress_sell_count_30d"] = float(len(sells))
            features["congress_net_trades_30d"] = float(len(buys) - len(sells))

            # Estimate total value from amount_range strings
            def _parse_amount(ar: str) -> float:
                """Extract midpoint from amount range like '$1,001 - $15,000'."""
                try:
                    parts = ar.replace("$", "").replace(",", "").split("-")
                    nums = [float(p.strip()) for p in parts if p.strip()]
                    return sum(nums) / len(nums) if nums else 0.0
                except Exception:
                    return 0.0

            total_val = sum(_parse_amount(t.amount_range) for t in recent)
            features["congress_total_value_30d"] = float(total_val)
        except Exception:
            for k in ["congress_buy_count_30d", "congress_sell_count_30d",
                       "congress_net_trades_30d", "congress_total_value_30d"]:
                features[k] = _np.nan

        # Insider trades
        try:
            ins = await self.get_insider_trades(ticker)
            from datetime import timedelta as _td2

            cutoff_90d = _ref_date - _td2(days=90)
            recent_ins = [t for t in ins if t.filing_date and
                          t.filing_date >= cutoff_90d.isoformat()]
            ins_buys = [t for t in recent_ins if "buy" in t.transaction_type.lower()
                        or "purchase" in t.transaction_type.lower()]
            ins_sells = [t for t in recent_ins if "sell" in t.transaction_type.lower()
                         or "sale" in t.transaction_type.lower()]
            features["insider_uw_buy_count_90d"] = float(len(ins_buys))
            features["insider_uw_sell_count_90d"] = float(len(ins_sells))
            features["insider_uw_net_shares_90d"] = float(
                sum(t.shares for t in ins_buys) - sum(t.shares for t in ins_sells)
            )
            total_ins = len(ins_buys) + len(ins_sells)
            features["insider_uw_buy_sell_ratio"] = (
                float(len(ins_buys) / total_ins) if total_ins > 0 else _np.nan
            )
            if recent_ins:
                dates = [t.filing_date for t in recent_ins if t.filing_date]
                if dates:
                    most_recent = max(dates)
                    try:
                        from datetime import date as _date
                        days_ago = (_ref_date - _date.fromisoformat(most_recent)).days
                        features["insider_uw_latest_days_ago"] = float(days_ago)
                    except Exception:
                        features["insider_uw_latest_days_ago"] = _np.nan
                else:
                    features["insider_uw_latest_days_ago"] = _np.nan
            else:
                features["insider_uw_latest_days_ago"] = _np.nan
        except Exception:
            for k in ["insider_uw_buy_count_90d", "insider_uw_sell_count_90d",
                       "insider_uw_net_shares_90d", "insider_uw_buy_sell_ratio",
                       "insider_uw_latest_days_ago"]:
                features[k] = _np.nan

        # Short interest
        try:
            si = await self.get_short_interest(ticker)
            features["short_interest_pct"] = _sf(si.short_percent_of_float)
            features["short_interest_days_to_cover"] = _sf(si.days_to_cover)
            features["short_utilization"] = _sf(si.short_interest)
            features["short_interest_change_30d"] = _sf(si.change_pct)
        except Exception:
            for k in ["short_interest_pct", "short_interest_days_to_cover",
                       "short_utilization", "short_interest_change_30d"]:
                features[k] = _np.nan

        # Institutional
        try:
            inst = await self.get_institutional_activity(ticker)
            features["institutional_ownership_pct"] = _sf(inst.institutional_ownership_pct)
            features["institutional_count"] = _sf(inst.num_holders, 0.0)
            features["institutional_net_change_qtr"] = _sf(inst.change_in_shares, 0.0)
            # Top-10 concentration
            holders = inst.top_holders or []
            if holders and inst.total_institutional_shares > 0:
                top10_shares = sum(
                    float(h.get("shares", 0)) for h in holders[:10]
                )
                features["top10_concentration"] = _sf(
                    top10_shares / inst.total_institutional_shares
                )
            else:
                features["top10_concentration"] = _np.nan
        except Exception:
            for k in ["institutional_ownership_pct", "institutional_count",
                       "institutional_net_change_qtr", "top10_concentration"]:
                features[k] = _np.nan

        # Volatility surface
        try:
            vs = await self.get_volatility_surface(ticker)
            features["iv_term_structure_slope"] = (
                _sf((vs.atm_iv_60d - vs.atm_iv_30d) / vs.atm_iv_30d)
                if vs.atm_iv_30d and vs.atm_iv_60d and vs.atm_iv_30d > 0
                else _np.nan
            )
            features["iv_skew_25d"] = _sf(vs.skew_25d)
            features["vol_surface_atm_30d"] = _sf(vs.atm_iv_30d)
            features["vol_surface_atm_60d"] = _sf(vs.atm_iv_60d)
            features["vol_smile_curvature"] = _sf(vs.butterfly_25d)
            features["iv_term_spread_30_60"] = (
                _sf(vs.atm_iv_30d - vs.atm_iv_60d)
                if vs.atm_iv_30d is not None and vs.atm_iv_60d is not None
                else _np.nan
            )
        except Exception:
            for k in ["iv_term_structure_slope", "iv_skew_25d",
                       "vol_surface_atm_30d", "vol_surface_atm_60d",
                       "vol_smile_curvature", "iv_term_spread_30_60"]:
                features[k] = _np.nan

        return features

    async def health_check(self) -> bool:
        """Check if the API is reachable and token is valid."""
        try:
            await self._request("GET", "/api/market/tide")
            return True
        except Exception:
            return False
