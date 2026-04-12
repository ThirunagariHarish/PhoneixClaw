"""
Macro economic data fetcher using yfinance.

Provides market regime classification, economic indicators, and calendar events.
Caching via Redis (5-minute TTL) to avoid redundant API calls.
"""

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", None)
CACHE_TTL = 300  # 5 minutes

# Ticker proxies for macro indicators
MACRO_TICKERS = {
    "spy": "SPY",       # S&P 500
    "qqq": "QQQ",       # Nasdaq 100
    "iwm": "IWM",       # Russell 2000
    "vix": "^VIX",      # Volatility
    "tnx": "^TNX",      # 10-Year Treasury yield
    "dxy": "UUP",       # Dollar proxy ETF
    "gld": "GLD",       # Gold
    "tlt": "TLT",       # Long-term Treasury bonds
    "oil": "USO",       # Oil
    "btc": "BTC-USD",   # Bitcoin
}

# Known economic calendar events (updated periodically)
ECONOMIC_CALENDAR_2026 = [
    {"date": "2026-01-28", "event": "FOMC Meeting", "importance": "high"},
    {"date": "2026-01-29", "event": "FOMC Decision", "importance": "high"},
    {"date": "2026-02-12", "event": "CPI Report", "importance": "high"},
    {"date": "2026-03-07", "event": "Non-Farm Payrolls", "importance": "high"},
    {"date": "2026-03-18", "event": "FOMC Meeting", "importance": "high"},
    {"date": "2026-03-19", "event": "FOMC Decision", "importance": "high"},
    {"date": "2026-04-10", "event": "CPI Report", "importance": "high"},
    {"date": "2026-05-06", "event": "FOMC Meeting", "importance": "high"},
    {"date": "2026-05-07", "event": "FOMC Decision", "importance": "high"},
    {"date": "2026-05-08", "event": "Non-Farm Payrolls", "importance": "high"},
    {"date": "2026-05-13", "event": "CPI Report", "importance": "high"},
    {"date": "2026-06-17", "event": "FOMC Meeting", "importance": "high"},
    {"date": "2026-06-18", "event": "FOMC Decision", "importance": "high"},
    {"date": "2026-07-15", "event": "CPI Report", "importance": "high"},
    {"date": "2026-07-29", "event": "FOMC Meeting", "importance": "high"},
    {"date": "2026-07-30", "event": "FOMC Decision", "importance": "high"},
    {"date": "2026-09-16", "event": "FOMC Meeting", "importance": "high"},
    {"date": "2026-09-17", "event": "FOMC Decision", "importance": "high"},
    {"date": "2026-11-04", "event": "FOMC Meeting", "importance": "high"},
    {"date": "2026-11-05", "event": "FOMC Decision", "importance": "high"},
    {"date": "2026-12-16", "event": "FOMC Meeting", "importance": "high"},
    {"date": "2026-12-17", "event": "FOMC Decision", "importance": "high"},
]


class MacroDataFetcher:
    """Fetches macro economic data from yfinance with Redis caching."""

    def __init__(self, redis_url: str | None = REDIS_URL, cache_ttl: int = CACHE_TTL):
        self._redis_url = redis_url
        self._cache_ttl = cache_ttl
        self._redis = None

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        if not self._redis_url:
            return None
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(self._redis_url)
            return self._redis
        except Exception as e:
            logger.warning("Redis unavailable for macro cache: %s", e)
            return None

    async def _cache_get(self, key: str) -> dict | None:
        r = await self._get_redis()
        if not r:
            return None
        try:
            raw = await r.get(f"macro:{key}")
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def _cache_set(self, key: str, data: dict) -> None:
        r = await self._get_redis()
        if not r:
            return
        try:
            await r.set(f"macro:{key}", json.dumps(data, default=str), ex=self._cache_ttl)
        except Exception:
            pass

    async def get_indicators(self) -> list[dict]:
        """Fetch current values for key macro indicators."""
        cached = await self._cache_get("indicators")
        if cached:
            return cached

        indicators = []
        try:
            import yfinance as yf

            tickers_str = " ".join(MACRO_TICKERS.values())
            data = yf.download(tickers_str, period="5d", interval="1d", progress=False, threads=True)

            for name, symbol in MACRO_TICKERS.items():
                try:
                    if symbol in data["Close"].columns:
                        closes = data["Close"][symbol].dropna()
                    else:
                        closes = data["Close"].dropna()

                    if len(closes) < 2:
                        continue

                    current = float(closes.iloc[-1])
                    prev = float(closes.iloc[-2])
                    change = current - prev
                    change_pct = (change / prev * 100) if prev != 0 else 0

                    # Determine trend direction from daily change
                    if change_pct > 0.1:
                        trend = "up"
                    elif change_pct < -0.1:
                        trend = "down"
                    else:
                        trend = "neutral"

                    display_name = name.upper()
                    # Format value as string for frontend display
                    if name in ("vix", "tnx"):
                        display_value = f"{current:.2f}"
                    elif name in ("btc",):
                        display_value = f"${current:,.0f}"
                    else:
                        display_value = f"${current:.2f}"

                    indicators.append({
                        "name": display_name,
                        "symbol": symbol,
                        "value": display_value,
                        "numeric_value": round(current, 2),
                        "change": round(change, 2),
                        "change_pct": round(change_pct, 2),
                        "trend": trend,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception as e:
                    logger.debug("Failed to process %s: %s", symbol, e)
        except ImportError:
            logger.error("yfinance not installed")
        except Exception as e:
            logger.error("Failed to fetch macro indicators: %s", e)

        await self._cache_set("indicators", indicators)
        return indicators

    async def get_regime(self) -> dict:
        """Classify current market regime based on VIX, yield curve, and momentum."""
        cached = await self._cache_get("regime")
        if cached:
            return cached

        regime = {"regime": "UNKNOWN", "confidence": 0, "signals": [], "updated_at": datetime.now(timezone.utc).isoformat()}

        try:
            import yfinance as yf

            vix_data = yf.download("^VIX", period="1mo", interval="1d", progress=False)
            spy_data = yf.download("SPY", period="3mo", interval="1d", progress=False)

            if vix_data.empty or spy_data.empty:
                return regime

            vix_current = float(vix_data["Close"].iloc[-1])
            vix_avg = float(vix_data["Close"].mean())

            spy_closes = spy_data["Close"].squeeze()
            spy_sma20 = float(spy_closes.rolling(20).mean().iloc[-1])
            spy_sma50 = float(spy_closes.rolling(50).mean().iloc[-1])
            spy_current = float(spy_closes.iloc[-1])

            signals = []
            score = 0  # positive = risk-on, negative = risk-off

            # VIX regime
            if vix_current < 15:
                signals.append({"indicator": "VIX", "signal": "Low volatility (complacency)", "value": round(vix_current, 1)})
                score += 1
            elif vix_current < 20:
                signals.append({"indicator": "VIX", "signal": "Normal volatility", "value": round(vix_current, 1)})
            elif vix_current < 30:
                signals.append({"indicator": "VIX", "signal": "Elevated volatility", "value": round(vix_current, 1)})
                score -= 1
            else:
                signals.append({"indicator": "VIX", "signal": "Fear / crisis", "value": round(vix_current, 1)})
                score -= 2

            # Trend via SMA alignment
            if spy_current > spy_sma20 > spy_sma50:
                signals.append({"indicator": "SPY Trend", "signal": "Bullish SMA alignment", "value": round(spy_current, 2)})
                score += 2
            elif spy_current < spy_sma20 < spy_sma50:
                signals.append({"indicator": "SPY Trend", "signal": "Bearish SMA alignment", "value": round(spy_current, 2)})
                score -= 2
            else:
                signals.append({"indicator": "SPY Trend", "signal": "Mixed / transitioning", "value": round(spy_current, 2)})

            # VIX vs average
            if vix_current < vix_avg * 0.8:
                signals.append({"indicator": "VIX vs Avg", "signal": "Below average — risk-on", "value": round(vix_current / vix_avg, 2)})
                score += 1
            elif vix_current > vix_avg * 1.2:
                signals.append({"indicator": "VIX vs Avg", "signal": "Above average — risk-off", "value": round(vix_current / vix_avg, 2)})
                score -= 1

            # Classify
            if score >= 3:
                regime_label = "RISK_ON"
                confidence = min(0.9, 0.5 + score * 0.1)
            elif score >= 1:
                regime_label = "RISK_ON"
                confidence = 0.5 + score * 0.1
            elif score <= -3:
                regime_label = "RISK_OFF"
                confidence = min(0.9, 0.5 + abs(score) * 0.1)
            elif score <= -1:
                regime_label = "RISK_OFF"
                confidence = 0.5 + abs(score) * 0.1
            else:
                regime_label = "TRANSITION"
                confidence = 0.4

            regime = {
                "regime": regime_label,
                "confidence": round(confidence, 2),
                "score": score,
                "signals": signals,
                "vix": round(vix_current, 2),
                "spy": round(spy_current, 2),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        except ImportError:
            logger.error("yfinance not installed")
        except Exception as e:
            logger.error("Failed to compute regime: %s", e)

        await self._cache_set("regime", regime)
        return regime

    async def get_calendar(self, limit: int = 10) -> list[dict]:
        """Return upcoming economic calendar events with frontend-compatible fields."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        upcoming = [e for e in ECONOMIC_CALENDAR_2026 if e["date"] >= today]
        result = []
        for i, e in enumerate(upcoming[:limit]):
            result.append({
                "id": f"cal-{i}",
                "date": e["date"],
                "event": e["event"],
                "impact": e.get("importance", "medium").upper(),
                "importance": e.get("importance", "medium"),
            })
        return result

    async def close(self):
        if self._redis:
            await self._redis.aclose()
            self._redis = None
