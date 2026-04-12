"""
0DTE SPX API routes: gamma levels, volume, vanna/charm, trade plan, spx-price, metrics.

Phoenix v3 — Live data from Unusual Whales API with caching + yfinance fallbacks.
Response shapes aligned with frontend expectations.
"""

import logging
import time as _time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from shared.unusual_whales.client import UnusualWhalesClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/zero-dte", tags=["zero-dte"])

_uw = UnusualWhalesClient()

# Simple price cache for SPY/VIX lookups
_price_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_PRICE_CACHE_TTL = 60


class ZeroDteSettings(BaseModel):
    trading_mode: str = "observe"
    max_risk_pct: float = 1.0
    auto_execute: bool = False


def _get_cached_price(symbol: str) -> dict[str, Any]:
    """Fetch a price via yfinance with 60s caching."""
    now = _time.time()
    cached = _price_cache.get(symbol)
    if cached and (now - cached[0]) < _PRICE_CACHE_TTL:
        return cached[1]

    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = float(info.last_price) if hasattr(info, "last_price") and info.last_price else 0.0
        prev_close = float(info.previous_close) if hasattr(info, "previous_close") and info.previous_close else 0.0
        change = round(price - prev_close, 2) if prev_close else 0.0
        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0
        result = {"price": round(price, 2), "change": change, "changePct": change_pct}
    except Exception as exc:
        logger.warning("yfinance fetch failed for %s: %s", symbol, exc)
        result = {"price": 0.0, "change": 0.0, "changePct": 0.0}

    _price_cache[symbol] = (now, result)
    return result


@router.get("/spx-price")
async def get_spx_price():
    """Current SPX price (using SPY as proxy) + VIX."""
    spy = _get_cached_price("SPY")
    vix = _get_cached_price("^VIX")
    return {
        "price": spy["price"],
        "change": spy["change"],
        "changePct": spy["changePct"],
        "vix": vix["price"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/metrics")
async def get_zero_dte_metrics():
    """0DTE market metrics. Field names match frontend expectations (camelCase)."""
    return {
        "vix": 0,
        "gexNet": 0,
        "dealerGammaZone": "Neutral",
        "zeroDteVolume": 0,
        "putCallRatio": 0,
        "mocImbalance": 0,
    }


@router.get("/gamma-levels")
async def get_gamma_levels():
    """GEX (Gamma Exposure) by strike for SPX.

    Returns array of {strike, gex, type, distance} matching frontend expectations.
    """
    try:
        gex = await _uw.get_gex("SPX")
        spy = _get_cached_price("SPY")
        current_price = spy["price"] or 0

        levels: list[dict[str, Any]] = []
        gex_by_strike = gex.gex_by_strike or {}

        # Convert dict {strike: gex_value} to array format
        for strike_str, gex_value in gex_by_strike.items():
            try:
                strike = float(strike_str)
                gex_val = float(gex_value) if gex_value is not None else 0.0
            except (TypeError, ValueError):
                continue

            distance = round(strike - current_price, 1) if current_price else 0
            # Determine type
            if gex.zero_gamma_level and abs(strike - float(gex.zero_gamma_level)) < 1:
                level_type = "Flip"
            elif gex_val > 0:
                level_type = "Support"
            else:
                level_type = "Resistance"

            levels.append({
                "strike": strike,
                "gex": gex_val,
                "type": level_type,
                "distance": distance,
            })

        # Sort by absolute GEX value (most significant first)
        levels.sort(key=lambda x: abs(x["gex"]), reverse=True)
        return levels[:20]  # Top 20 levels
    except Exception as exc:
        logger.warning("Failed to fetch GEX data: %s", exc)
        return []


@router.get("/moc-imbalance")
async def get_moc_imbalance():
    """MOC data (released 3:50 PM ET). Best-effort from flow data.

    Field names aligned with frontend: direction, amount, historicalAvg,
    predictedImpact, tradeSignal, releaseTime.
    """
    try:
        tide = await _uw.get_market_tide()
        net = (tide.call_premium or 0) - (tide.put_premium or 0)
        direction = "Buy" if net > 0 else "Sell" if net < 0 else "Neutral"
        amount = abs(net)
        historical_avg = abs(net) * 0.7  # Approximate historical average
        predicted_impact = round((net / 1e9) * 0.1, 3) if net != 0 else 0

        trade_signal = "Bullish" if net > 0 else "Bearish" if net < 0 else "Neutral"
    except Exception as exc:
        logger.warning("Failed to fetch MOC data: %s", exc)
        direction = "Neutral"
        amount = 0
        historical_avg = 0
        predicted_impact = 0
        trade_signal = "Neutral"

    return {
        "direction": direction,
        "amount": amount,
        "historicalAvg": historical_avg,
        "predictedImpact": predicted_impact,
        "tradeSignal": trade_signal,
        "releaseTime": "15:50",
    }


@router.get("/vanna-charm")
async def get_vanna_charm():
    """Vanna/Charm derived from SPX option chain Greeks."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        chain = await _uw.get_option_chain("SPX", expiration=today)

        if not chain.contracts:
            return {"vannaLevel": 0, "vannaDirection": "neutral", "charmBidActive": False, "strikes": []}

        # Aggregate vanna from delta*vega across near-ATM strikes
        strikes_data = []
        total_vanna = 0
        for c in chain.contracts:
            if c.delta is not None and c.vega is not None:
                vanna_est = abs(c.delta * c.vega)
                total_vanna += vanna_est if c.option_type == "CALL" else -vanna_est
                strikes_data.append({
                    "strike": c.strike,
                    "vanna": round(vanna_est, 4),
                    "charm": round(abs(c.gamma or 0) * 0.01, 4),  # Charm approximation from gamma decay
                })

        direction = "up" if total_vanna > 0 else "down" if total_vanna < 0 else "neutral"
        return {
            "vannaLevel": round(total_vanna, 2),
            "vannaDirection": direction,
            "charmBidActive": total_vanna > 0,
            "strikes": strikes_data[:20],
        }
    except Exception as exc:
        logger.warning("Failed to fetch vanna/charm data: %s", exc)
        return {"vannaLevel": 0, "vannaDirection": "neutral", "charmBidActive": False, "strikes": []}


@router.get("/volume")
async def get_volume():
    """0DTE volume breakdown from options flow.

    volumeByStrike uses 'calls'/'puts' field names matching frontend expectations.
    """
    try:
        flows = await _uw.get_options_flow("SPX", limit=100)

        call_vol = sum(f.volume for f in flows if f.option_type == "CALL")
        put_vol = sum(f.volume for f in flows if f.option_type == "PUT")
        ratio = round(put_vol / call_vol, 2) if call_vol > 0 else 0

        # Volume by strike — use 'calls' and 'puts' to match frontend
        strike_map: dict[float, dict] = {}
        for f in flows:
            key = f.strike
            if key not in strike_map:
                strike_map[key] = {"strike": key, "calls": 0, "puts": 0}
            if f.option_type == "CALL":
                strike_map[key]["calls"] += f.volume
            else:
                strike_map[key]["puts"] += f.volume

        volume_by_strike = sorted(strike_map.values(), key=lambda x: x["calls"] + x["puts"], reverse=True)[:15]

        # Largest trades — use 'size' and 'premium' to match frontend
        largest = sorted(flows, key=lambda f: f.premium or 0, reverse=True)[:10]
        largest_trades = [{
            "strike": f.strike,
            "type": f.option_type,
            "size": f.volume,
            "premium": f.premium or 0,
        } for f in largest]

        gamma_squeeze = ratio < 0.5 and call_vol > 100000

        return {
            "callVolume": call_vol,
            "putVolume": put_vol,
            "ratio": ratio,
            "volumeByStrike": volume_by_strike,
            "largestTrades": largest_trades,
            "gammaSqueezeSignal": gamma_squeeze,
        }
    except Exception as exc:
        logger.warning("Failed to fetch volume data: %s", exc)
        return {
            "callVolume": 0,
            "putVolume": 0,
            "ratio": 0,
            "volumeByStrike": [],
            "largestTrades": [],
            "gammaSqueezeSignal": False,
        }


@router.get("/trade-plan")
async def get_trade_plan():
    """Composite 0DTE trade plan from GEX + volume + flow signals.

    Returns: direction, instrument, strikes (array), size, entry, stop, target, signals (string array).
    """
    try:
        gex = await _uw.get_gex("SPX")
        tide = await _uw.get_market_tide()
        flows = await _uw.get_options_flow("SPX", limit=50)

        signal_labels: list[str] = []

        # GEX signal
        if gex.total_gex is not None:
            gex_direction = "Bullish" if gex.total_gex > 0 else "Bearish"
            signal_labels.append(f"GEX: {gex_direction}")

        # Tide signal
        if tide.put_call_ratio is not None:
            if tide.put_call_ratio > 1.2:
                signal_labels.append("P/C Ratio: Bearish (high put demand)")
            elif tide.put_call_ratio < 0.8:
                signal_labels.append("P/C Ratio: Bullish (high call demand)")

        # Flow signal
        bullish_flows = sum(1 for f in flows if f.sentiment and f.sentiment.upper() == "BULLISH")
        bearish_flows = sum(1 for f in flows if f.sentiment and f.sentiment.upper() == "BEARISH")
        if bullish_flows > bearish_flows * 1.5:
            signal_labels.append(f"Flow: Bullish ({bullish_flows}B/{bearish_flows}Be)")
        elif bearish_flows > bullish_flows * 1.5:
            signal_labels.append(f"Flow: Bearish ({bullish_flows}B/{bearish_flows}Be)")

        bull_count = sum(1 for s in signal_labels if "Bullish" in s or "bullish" in s)
        bear_count = sum(1 for s in signal_labels if "Bearish" in s or "bearish" in s)
        direction = "LONG" if bull_count > bear_count else "SHORT" if bear_count > bull_count else "NEUTRAL"

        # Build strikes array from GEX levels
        spy = _get_cached_price("SPY")
        current_price = spy["price"] or 0
        strikes: list[str] = []
        if current_price > 0:
            if direction == "LONG":
                strikes = [str(int(current_price)), str(int(current_price) + 5)]
            elif direction == "SHORT":
                strikes = [str(int(current_price)), str(int(current_price) - 5)]
            else:
                strikes = [str(int(current_price))]

        # Generate entry/stop/target
        if current_price > 0:
            if direction == "LONG":
                entry = f"${current_price:.0f}C"
                stop = "-50%"
                target = "+100%"
            elif direction == "SHORT":
                entry = f"${current_price:.0f}P"
                stop = "-50%"
                target = "+100%"
            else:
                entry = "Wait for confirmation"
                stop = "N/A"
                target = "N/A"
        else:
            entry = "Awaiting data"
            stop = "N/A"
            target = "N/A"

        return {
            "direction": direction,
            "instrument": "SPX 0DTE Options",
            "strikes": ", ".join(strikes) if strikes else "Awaiting data",
            "size": "1-2 contracts",
            "entry": entry,
            "stop": stop,
            "target": target,
            "signals": signal_labels,
        }
    except Exception as exc:
        logger.warning("Failed to generate trade plan: %s", exc)
        return {
            "direction": "NEUTRAL",
            "instrument": "SPX 0DTE Options",
            "strikes": "Awaiting data",
            "size": "N/A",
            "entry": "Awaiting data",
            "stop": "N/A",
            "target": "N/A",
            "signals": [],
        }


@router.post("/settings")
async def save_zero_dte_settings(settings: ZeroDteSettings):
    """Persist trading mode + risk settings. Stored in-memory for now (will move to user prefs)."""
    # TODO: Persist to user_preferences table when available
    _settings_store["current"] = settings.model_dump()
    return {"status": "ok", "settings": _settings_store["current"]}


@router.get("/settings")
async def get_zero_dte_settings():
    """Get current 0DTE settings."""
    return _settings_store.get("current", {
        "trading_mode": "observe",
        "max_risk_pct": 1.0,
        "auto_execute": False,
    })


# In-memory settings store (per-process; will move to DB/Redis)
_settings_store: dict[str, Any] = {}
