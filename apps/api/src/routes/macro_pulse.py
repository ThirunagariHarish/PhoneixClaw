"""
Macro-Pulse API routes: regime, calendar, indicators, yield curve, FRED data, sparklines.

Phoenix v3 — Live macro data from yfinance with Redis caching.
"""

import logging

from fastapi import APIRouter, Query

from shared.market.macro import MacroDataFetcher

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/macro-pulse", tags=["macro-pulse"])

_fetcher = MacroDataFetcher()


@router.get("/regime")
async def get_regime():
    """Current market regime assessment (risk-on / risk-off / transition)."""
    return await _fetcher.get_regime()


@router.get("/calendar")
async def get_calendar(limit: int = Query(10, ge=1, le=50)):
    """Upcoming economic calendar: FOMC, CPI, NFP, GDP with consensus/actual/surprise."""
    events = await _fetcher.get_calendar(limit=limit)

    # Add forecast/actual/surprise columns where available
    for ev in events:
        ev.setdefault("forecast", None)
        ev.setdefault("actual", None)
        ev.setdefault("surprise", None)
        ev.setdefault("prior", None)

    return events


@router.get("/indicators")
async def get_indicators():
    """Live macro indicators: VIX, 10Y, DXY, gold, oil, SPY, QQQ, BTC."""
    return await _fetcher.get_indicators()


@router.get("/indicator-history")
async def get_indicator_history(
    symbol: str = Query("^VIX"),
    period: str = Query("30d"),
):
    """Historical data for a single indicator — for sparkline/line charts."""
    try:
        import yfinance as yf

        data = yf.download(symbol, period=period, interval="1d", progress=False)
        if data.empty:
            return {"symbol": symbol, "history": []}

        closes = data["Close"].squeeze().dropna()
        history = []
        for dt, val in closes.items():
            try:
                date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
                float_val = float(val)
                if float_val != float_val:  # NaN check
                    continue
                history.append({"date": date_str, "value": round(float_val, 2)})
            except (ValueError, TypeError):
                continue
        return {"symbol": symbol, "history": history}
    except ImportError:
        logger.error("yfinance not installed")
        return {"symbol": symbol, "history": []}
    except Exception as e:
        logger.error("Failed to fetch indicator history for %s: %s", symbol, e)
        return {"symbol": symbol, "history": []}


@router.get("/sparklines")
async def get_sparklines():
    """VIX, 10Y yield, DXY 30-day sparkline data for multi-indicator charts."""
    import asyncio

    symbols = {"VIX": "^VIX", "10Y": "^TNX", "DXY": "UUP"}
    results = {}

    async def _fetch_one(name: str, symbol: str):
        try:
            import yfinance as yf

            data = yf.download(symbol, period="30d", interval="1d", progress=False)
            if data.empty:
                return name, []
            closes = data["Close"].squeeze().dropna()
            points = []
            for dt, val in closes.items():
                try:
                    date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
                    float_val = float(val)
                    if float_val != float_val:
                        continue
                    points.append({"date": date_str, "value": round(float_val, 2)})
                except (ValueError, TypeError):
                    continue
            return name, points
        except Exception as e:
            logger.debug("Sparkline fetch failed for %s: %s", symbol, e)
            return name, []

    tasks = [_fetch_one(name, symbol) for name, symbol in symbols.items()]
    completed = await asyncio.gather(*tasks, return_exceptions=True)
    for item in completed:
        if isinstance(item, tuple):
            results[item[0]] = item[1]
    return results


@router.get("/yield-curve")
async def get_yield_curve():
    """Yield curve: 2s10s spread chart + full curve (2Y, 5Y, 10Y, 30Y)."""
    try:
        import yfinance as yf

        # Fetch all yield data
        # ^FVX = 5Y, ^TNX = 10Y, ^TYX = 30Y
        # 2Y is not directly on Yahoo; use ^IRX (13-week T-bill) as proxy or estimate
        tickers_str = "^IRX ^FVX ^TNX ^TYX"
        data = yf.download(tickers_str, period="6mo", interval="1d", progress=False)

        if data.empty:
            return {"curve": [], "spread_history": []}

        # Current yield curve point values
        curve_points = []
        label_map = {"^IRX": "3M", "^FVX": "5Y", "^TNX": "10Y", "^TYX": "30Y"}
        maturity_order = {"3M": 0.25, "5Y": 5, "10Y": 10, "30Y": 30}

        for symbol, label in label_map.items():
            try:
                if symbol in data["Close"].columns:
                    closes = data["Close"][symbol].dropna()
                else:
                    continues = data["Close"].dropna()
                    closes = continues
                if len(closes) > 0:
                    val = float(closes.iloc[-1])
                    if val == val:  # NaN check
                        curve_points.append({
                            "maturity": label,
                            "yield_pct": round(val, 3),
                            "maturity_years": maturity_order.get(label, 0),
                        })
            except Exception:
                continue

        curve_points.sort(key=lambda x: x["maturity_years"])

        # 2s10s spread history (approximate: use 10Y - 3M as proxy since 2Y not on Yahoo)
        spread_history = []
        try:
            if "^TNX" in data["Close"].columns and "^IRX" in data["Close"].columns:
                tnx = data["Close"]["^TNX"].dropna()
                irx = data["Close"]["^IRX"].dropna()
                # Align indices
                common_idx = tnx.index.intersection(irx.index)
                for dt in common_idx:
                    try:
                        t10 = float(tnx.loc[dt])
                        t3m = float(irx.loc[dt])
                        if t10 != t10 or t3m != t3m:
                            continue
                        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
                        spread_history.append({
                            "date": date_str,
                            "spread": round(t10 - t3m, 3),
                            "tenY": round(t10, 3),
                            "threeM": round(t3m, 3),
                        })
                    except (ValueError, TypeError):
                        continue
        except Exception as e:
            logger.debug("Spread history failed: %s", e)

        return {"curve": curve_points, "spread_history": spread_history}
    except ImportError:
        logger.error("yfinance not installed")
        return {"curve": [], "spread_history": []}
    except Exception as e:
        logger.error("Failed to compute yield curve: %s", e)
        return {"curve": [], "spread_history": []}


@router.get("/fred-indicators")
async def get_fred_indicators():
    """FRED data: GDP, unemployment, CPI history from shared fred_client."""
    try:
        from shared.data.fred_client import get_fred_client

        fred = get_fred_client()
        results = {}

        # GDP growth (quarterly)
        try:
            gdp = fred.get_series("GDPC1")
            if not gdp.empty:
                gdp_points = []
                for dt, val in gdp.tail(20).items():
                    try:
                        v = float(val)
                        if v != v:
                            continue
                        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
                        gdp_points.append({"date": date_str, "value": round(v, 2)})
                    except (ValueError, TypeError):
                        continue
                results["gdp"] = gdp_points
            else:
                results["gdp"] = []
        except Exception:
            results["gdp"] = []

        # Unemployment rate (monthly)
        try:
            unrate = fred.get_series("UNRATE")
            if not unrate.empty:
                unrate_points = []
                for dt, val in unrate.tail(24).items():
                    try:
                        v = float(val)
                        if v != v:
                            continue
                        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
                        unrate_points.append({"date": date_str, "value": round(v, 2)})
                    except (ValueError, TypeError):
                        continue
                results["unemployment"] = unrate_points
            else:
                results["unemployment"] = []
        except Exception:
            results["unemployment"] = []

        # CPI index (monthly)
        try:
            cpi = fred.get_series("CPIAUCSL")
            if not cpi.empty:
                cpi_points = []
                # Compute YoY change
                cpi_clean = cpi.dropna()
                for i in range(12, len(cpi_clean)):
                    try:
                        current = float(cpi_clean.iloc[i])
                        prev_year = float(cpi_clean.iloc[i - 12])
                        if current != current or prev_year != prev_year or prev_year == 0:
                            continue
                        yoy = round((current / prev_year - 1) * 100, 2)
                        dt = cpi_clean.index[i]
                        date_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
                        cpi_points.append({"date": date_str, "value": yoy})
                    except (ValueError, TypeError):
                        continue
                results["cpi"] = cpi_points[-24:]  # last 24 months
            else:
                results["cpi"] = []
        except Exception:
            results["cpi"] = []

        return results
    except ImportError:
        logger.warning("fredapi not available")
        return {"gdp": [], "unemployment": [], "cpi": []}
    except Exception as e:
        logger.error("Failed to fetch FRED indicators: %s", e)
        return {"gdp": [], "unemployment": [], "cpi": []}


@router.get("/cpi")
async def get_cpi():
    """CPI trend data for chart display."""
    # Static recent CPI data (YoY %) — updated periodically
    return [
        {"month": "2025-07", "value": 3.2},
        {"month": "2025-08", "value": 3.1},
        {"month": "2025-09", "value": 3.0},
        {"month": "2025-10", "value": 2.9},
        {"month": "2025-11", "value": 2.8},
        {"month": "2025-12", "value": 2.7},
        {"month": "2026-01", "value": 2.8},
        {"month": "2026-02", "value": 2.7},
        {"month": "2026-03", "value": 2.6},
    ]


@router.get("/geopolitical")
async def get_geopolitical():
    """Geopolitical risks — placeholder until LLM integration."""
    return {
        "status": "pending",
        "message": "Geopolitical analysis requires LLM integration (Ollama/Claude)",
        "risks": [],
    }


@router.get("/implications")
async def get_implications():
    """AI-generated trade implications — placeholder until LLM integration."""
    return {"status": "pending", "message": "Trade implications require LLM integration", "implications": []}
