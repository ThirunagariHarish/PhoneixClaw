"""
On-Chain/Flow API routes: whale alerts, Mag 7, meme stocks, sectors, indices.

Phoenix v3 — Live options flow data from Unusual Whales API.
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query

from shared.unusual_whales.client import UnusualWhalesClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/onchain-flow", tags=["onchain-flow"])

_uw = UnusualWhalesClient()

MAG7_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"]
MEME_TICKERS = ["GME", "AMC", "PLTR", "RIVN", "SOFI", "MARA", "HOOD"]
INDEX_TICKERS = ["SPY", "QQQ", "IWM", "DIA"]
SECTOR_ETFS = {
    "Technology": "XLK", "Healthcare": "XLV", "Financials": "XLF",
    "Energy": "XLE", "Consumer Discretionary": "XLY", "Consumer Staples": "XLP",
    "Industrials": "XLI", "Materials": "XLB", "Utilities": "XLU",
    "Real Estate": "XLRE", "Communications": "XLC",
}


async def _get_ticker_flow_summary(ticker: str) -> dict:
    """Fetch flow for a single ticker and summarize."""
    flows = await _uw.get_options_flow(ticker, limit=30)
    if not flows:
        return {"ticker": ticker, "call_put_ratio": 0, "total_premium": 0, "sentiment": "NEUTRAL", "whale_trades": []}

    call_vol = sum(f.volume for f in flows if f.option_type == "CALL")
    put_vol = sum(f.volume for f in flows if f.option_type == "PUT")
    ratio = round(call_vol / put_vol, 2) if put_vol > 0 else (99.0 if call_vol > 0 else 0)
    total_premium = sum(f.premium or 0 for f in flows)

    bullish = sum(1 for f in flows if f.sentiment and f.sentiment.upper() == "BULLISH")
    bearish = sum(1 for f in flows if f.sentiment and f.sentiment.upper() == "BEARISH")
    if bullish > bearish * 1.5:
        inst_flow = "ACCUMULATING"
    elif bearish > bullish * 1.5:
        inst_flow = "DISTRIBUTING"
    else:
        inst_flow = "NEUTRAL"

    # Top whale trades (>$500k premium)
    whales = sorted(flows, key=lambda f: f.premium or 0, reverse=True)[:3]
    whale_strs = [
        f"${(f.premium or 0) / 1e6:.1f}M {f.option_type.lower()} {f.trade_type or 'block'} {f.strike}{f.option_type[0]}"
        for f in whales if (f.premium or 0) >= 500000
    ]

    # Dark pool percentage estimate (block trades as % of total)
    block_count = sum(1 for f in flows if f.trade_type and "block" in f.trade_type.lower())
    dp_pct = round(block_count / len(flows) * 100, 1) if flows else 0

    return {
        "ticker": ticker,
        "call_put_ratio": ratio,
        "total_premium": total_premium,
        "institutional_flow": inst_flow,
        "whale_trades": whale_strs,
        "dark_pool_pct": dp_pct,
    }


@router.get("/whale-alerts")
async def get_whale_alerts(min_premium: int = Query(500000, ge=0)):
    """Recent large options trades (whale alerts) across all tickers."""
    flows = await _uw.get_options_flow(limit=100)
    whales = [f for f in flows if (f.premium or 0) >= min_premium]
    whales.sort(key=lambda f: f.premium or 0, reverse=True)

    return [
        {
            "timestamp": f.timestamp or datetime.now(timezone.utc).isoformat(),
            "ticker": f.ticker,
            "type": f.option_type,
            "strike": f.strike,
            "size": f.volume,
            "premium": f.premium,
            "sentiment": f.sentiment or "UNKNOWN",
            "trade_type": f.trade_type,
        }
        for f in whales[:20]
    ]


@router.get("/metrics")
async def get_flow_metrics():
    """Aggregate flow metrics: whale count, unusual volume, dark pool %, institutional sentiment."""
    try:
        flows = await _uw.get_options_flow(limit=100)
    except Exception:
        flows = []

    whale_alerts = [f for f in flows if (f.premium or 0) >= 500_000]
    total_premium = sum(f.premium or 0 for f in flows)
    unusual_premium = sum(f.premium or 0 for f in whale_alerts)

    # Institutional sentiment from flow sentiment counts
    bullish = sum(1 for f in flows if f.sentiment and f.sentiment.upper() == "BULLISH")
    bearish = sum(1 for f in flows if f.sentiment and f.sentiment.upper() == "BEARISH")
    if bullish > bearish * 1.5:
        inst_sentiment = "ACCUMULATING"
    elif bearish > bullish * 1.5:
        inst_sentiment = "DISTRIBUTING"
    else:
        inst_sentiment = "NEUTRAL"

    def _fmt_money(val: float) -> str:
        if val >= 1e9:
            return f"${val / 1e9:.1f}B"
        if val >= 1e6:
            return f"${val / 1e6:.1f}M"
        if val >= 1e3:
            return f"${val / 1e3:.0f}K"
        return f"${val:.0f}"

    # Dark pool estimate: fraction of whale/block trades vs total
    dp_pct = round(len(whale_alerts) / len(flows) * 100, 1) if flows else 0

    return {
        "whale_alerts_24h": len(whale_alerts),
        "unusual_flow_volume": _fmt_money(unusual_premium) if unusual_premium else "$0",
        "dark_pool_activity": f"{dp_pct}%",
        "institutional_sentiment": inst_sentiment,
        "total_premium": _fmt_money(total_premium) if total_premium else "$0",
        "total_flow_count": len(flows),
    }


@router.get("/mag7")
async def get_mag7_flow():
    """Mag 7 options flow summary — parallelized."""
    summaries = await asyncio.gather(
        *[_get_ticker_flow_summary(ticker) for ticker in MAG7_TICKERS],
        return_exceptions=True,
    )
    fallback = {"call_put_ratio": 0, "total_premium": 0, "whale_trades": []}
    tickers = [
        s if isinstance(s, dict) else {"ticker": MAG7_TICKERS[i], **fallback}
        for i, s in enumerate(summaries)
    ]
    return {"tickers": tickers}


@router.get("/meme")
async def get_meme_flow():
    """Meme stock options flow with institutional direction — parallelized."""
    summaries = await asyncio.gather(
        *[_get_ticker_flow_summary(ticker) for ticker in MEME_TICKERS],
        return_exceptions=True,
    )
    tickers = []
    for i, s in enumerate(summaries):
        if isinstance(s, Exception):
            s = {"ticker": MEME_TICKERS[i], "call_put_ratio": 0, "total_premium": 0, "whale_trades": []}
        # Derive social sentiment from call/put ratio (proxy: >1.5 = bullish = high social)
        cp = s.get("call_put_ratio", 0)
        social = min(round((cp / 3.0) * 100, 0), 100) if cp > 0 else 0
        s["social_sentiment"] = social
        tickers.append(s)
    return {"tickers": tickers}


@router.get("/sectors")
async def get_sector_flow():
    """Sector flow via sector ETFs — parallelized."""
    sector_items = list(SECTOR_ETFS.items())
    summaries = await asyncio.gather(
        *[_get_ticker_flow_summary(etf) for _, etf in sector_items],
        return_exceptions=True,
    )
    sectors = []
    for i, (sector_name, etf) in enumerate(sector_items):
        summary = summaries[i]
        if isinstance(summary, Exception):
            summary = {"call_put_ratio": 0, "institutional_flow": "NEUTRAL", "total_premium": 0}
        cp_ratio = summary.get("call_put_ratio", 0)
        # flow_pct: positive if call-biased (>1.0), negative if put-biased
        flow_pct = round((cp_ratio - 1.0) * 100, 1) if cp_ratio else 0
        sectors.append({
            "sector": sector_name,
            "etf": etf,
            "net_direction": summary.get("institutional_flow", "NEUTRAL"),
            "call_put_ratio": cp_ratio,
            "total_premium": summary.get("total_premium", 0),
            "top_movers": [{"ticker": etf, "flow_pct": flow_pct}],
        })
    return {"sectors": sectors}


@router.get("/indices")
async def get_index_flow():
    """Index flow with GEX and volume data — parallelized."""

    async def _fetch_index(symbol: str) -> dict:
        gex, flows = await asyncio.gather(
            _uw.get_gex(symbol),
            _uw.get_options_flow(symbol, limit=50),
        )

        call_vol = sum(f.volume for f in flows if f.option_type == "CALL")
        put_vol = sum(f.volume for f in flows if f.option_type == "PUT")
        ratio = round(put_vol / call_vol, 2) if call_vol > 0 else 0

        def _fmt_gex(val: float | None) -> str:
            if val is None:
                return "N/A"
            if abs(val) >= 1e9:
                return f"${val / 1e9:.1f}B"
            if abs(val) >= 1e6:
                return f"${val / 1e6:.1f}M"
            return f"${val:,.0f}"

        total_vol = call_vol + put_vol
        return {
            "symbol": symbol,
            "gex_level": _fmt_gex(gex.total_gex),
            "odte_volume": f"{total_vol:,}" if total_vol else "0",
            "put_call_skew": ratio,
            "dark_pool_pct": round(put_vol / total_vol * 100, 1) if total_vol else 0,
            "gex_total": gex.total_gex,
            "call_gex": gex.call_gex,
            "put_gex": gex.put_gex,
            "zero_gamma": gex.zero_gamma_level,
            "call_volume": call_vol,
            "put_volume": put_vol,
        }

    results = await asyncio.gather(
        *[_fetch_index(symbol) for symbol in INDEX_TICKERS],
        return_exceptions=True,
    )
    idx_fallback = {"gex_level": "N/A", "odte_volume": "0", "put_call_skew": 0, "dark_pool_pct": 0}
    indices = [
        r if isinstance(r, dict) else {"symbol": INDEX_TICKERS[i], **idx_fallback}
        for i, r in enumerate(results)
    ]
    return {"indices": indices}


@router.get("/gex-by-strike")
async def get_gex_by_strike(ticker: str = Query("SPY")):
    """GEX by strike for a selected ticker — for bar chart visualization."""
    try:
        gex = await _uw.get_gex(ticker)
        strikes = []
        for strike_str, gex_val in sorted(gex.gex_by_strike.items(), key=lambda x: float(x[0])):
            try:
                strikes.append({
                    "strike": float(strike_str),
                    "gex": float(gex_val) if gex_val is not None else 0,
                })
            except (ValueError, TypeError):
                continue
        return {
            "ticker": ticker,
            "strikes": strikes,
            "total_gex": gex.total_gex,
            "zero_gamma": gex.zero_gamma_level,
        }
    except Exception as e:
        logger.error("Failed to fetch GEX by strike for %s: %s", ticker, e)
        return {"ticker": ticker, "strikes": [], "total_gex": None, "zero_gamma": None}


@router.get("/net-premium-flow")
async def get_net_premium_flow(ticker: str = Query("SPY")):
    """Cumulative call vs put premium over time for area chart."""
    try:
        flows = await _uw.get_options_flow(ticker, limit=100)
        if not flows:
            return {"ticker": ticker, "timeline": []}

        # Group by timestamp (minute buckets)
        from collections import defaultdict
        buckets: dict[str, dict] = defaultdict(lambda: {"call_premium": 0.0, "put_premium": 0.0})
        for f in flows:
            ts = f.timestamp
            if ts is None:
                continue
            if hasattr(ts, "strftime"):
                bucket_key = ts.strftime("%H:%M")
            else:
                bucket_key = str(ts)[:16]
            premium = f.premium or 0
            if f.option_type == "CALL":
                buckets[bucket_key]["call_premium"] += premium
            else:
                buckets[bucket_key]["put_premium"] += premium

        # Build cumulative timeline
        timeline = []
        cum_call = 0.0
        cum_put = 0.0
        for time_key in sorted(buckets.keys()):
            cum_call += buckets[time_key]["call_premium"]
            cum_put += buckets[time_key]["put_premium"]
            timeline.append({
                "time": time_key,
                "cumCallPremium": round(cum_call, 2),
                "cumPutPremium": round(cum_put, 2),
                "netPremium": round(cum_call - cum_put, 2),
            })
        return {"ticker": ticker, "timeline": timeline}
    except Exception as e:
        logger.error("Failed to build net premium flow for %s: %s", ticker, e)
        return {"ticker": ticker, "timeline": []}


@router.get("/dark-pool")
async def get_dark_pool(ticker: str = Query("SPY")):
    """Dark pool data for a ticker from Unusual Whales."""
    try:
        dp = await _uw.get_dark_pool(ticker)
        return {
            "ticker": ticker,
            "total_volume": dp.total_volume,
            "total_notional": dp.total_notional,
            "dp_percentage": dp.dp_percentage,
            "block_trades": dp.block_trades,
            "avg_trade_size": dp.avg_trade_size,
            "sentiment": dp.sentiment,
        }
    except Exception as e:
        logger.error("Failed to fetch dark pool for %s: %s", ticker, e)
        return {"ticker": ticker, "total_volume": 0, "total_notional": 0, "dp_percentage": None, "block_trades": 0}


@router.get("/dark-pool-multi")
async def get_dark_pool_multi(tickers: str = Query("SPY,QQQ,AAPL,NVDA,TSLA")):
    """Dark pool data for multiple tickers."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()][:10]

    async def _fetch_dp(t: str) -> dict:
        try:
            dp = await _uw.get_dark_pool(t)
            return {
                "ticker": t,
                "total_volume": dp.total_volume,
                "total_notional": dp.total_notional,
                "dp_percentage": dp.dp_percentage,
                "block_trades": dp.block_trades,
                "avg_trade_size": dp.avg_trade_size,
                "sentiment": dp.sentiment,
            }
        except Exception:
            return {"ticker": t, "total_volume": 0, "total_notional": 0, "dp_percentage": None, "block_trades": 0}

    results = await asyncio.gather(*[_fetch_dp(t) for t in ticker_list])
    return {"tickers": list(results)}


@router.get("/open-interest-changes")
async def get_open_interest_changes(ticker: str = Query("SPY")):
    """Open interest by strike for a ticker from the option chain."""
    try:
        chain = await _uw.get_option_chain(ticker)
        if not chain.contracts:
            return {"ticker": ticker, "strikes": []}

        # Group OI by strike
        from collections import defaultdict
        oi_by_strike: dict[float, dict] = defaultdict(lambda: {"call_oi": 0, "put_oi": 0, "call_vol": 0, "put_vol": 0})
        for c in chain.contracts:
            key = c.strike
            if c.option_type == "CALL":
                oi_by_strike[key]["call_oi"] += c.open_interest
                oi_by_strike[key]["call_vol"] += c.volume
            else:
                oi_by_strike[key]["put_oi"] += c.open_interest
                oi_by_strike[key]["put_vol"] += c.volume

        strikes = []
        for strike in sorted(oi_by_strike.keys()):
            data = oi_by_strike[strike]
            total_oi = data["call_oi"] + data["put_oi"]
            if total_oi > 0:
                strikes.append({
                    "strike": strike,
                    "callOI": data["call_oi"],
                    "putOI": data["put_oi"],
                    "callVol": data["call_vol"],
                    "putVol": data["put_vol"],
                    "totalOI": total_oi,
                })

        # Limit to top 30 strikes by total OI
        strikes.sort(key=lambda x: x["totalOI"], reverse=True)
        top_strikes = sorted(strikes[:30], key=lambda x: x["strike"])

        return {"ticker": ticker, "strikes": top_strikes}
    except Exception as e:
        logger.error("Failed to fetch OI changes for %s: %s", ticker, e)
        return {"ticker": ticker, "strikes": []}
