"""
Market data API routes: indices, movers, news, watchlist.

M2.15: Market overview dashboard.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v2/market", tags=["market"])


@router.get("/overview")
async def get_market_overview():
    """Aggregated market overview: indices, sentiment, key levels."""
    return {
        "indices": [
            {"symbol": "SPX", "name": "S&P 500", "price": 5218.42, "change": 18.73, "change_pct": 0.36},
            {"symbol": "NDX", "name": "Nasdaq 100", "price": 18342.15, "change": 92.61, "change_pct": 0.51},
            {"symbol": "DJI", "name": "Dow Jones", "price": 39127.80, "change": -45.20, "change_pct": -0.12},
            {"symbol": "VIX", "name": "CBOE Volatility", "price": 14.32, "change": -0.58, "change_pct": -3.89},
        ],
        "sentiment": "neutral",
        "market_phase": "regular_hours",
        "key_levels": {"spx_support": 5180, "spx_resistance": 5260},
    }


@router.get("/indices")
async def get_market_indices():
    """Return major market indices with price and daily change."""
    return {
        "indices": [
            {"symbol": "SPX", "name": "S&P 500", "price": 5218.42, "change": 18.73, "change_pct": 0.36},
            {"symbol": "NDX", "name": "Nasdaq 100", "price": 18342.15, "change": 92.61, "change_pct": 0.51},
            {"symbol": "DJI", "name": "Dow Jones", "price": 39127.80, "change": -45.20, "change_pct": -0.12},
            {"symbol": "VIX", "name": "CBOE Volatility", "price": 14.32, "change": -0.58, "change_pct": -3.89},
            {"symbol": "DXY", "name": "US Dollar Index", "price": 104.15, "change": 0.22, "change_pct": 0.21},
        ]
    }


@router.get("/movers")
async def get_top_movers():
    """Return top market movers by absolute percent change."""
    return {
        "gainers": [
            {"symbol": "SMCI", "price": 892.40, "change_pct": 12.34},
            {"symbol": "NVDA", "price": 878.50, "change_pct": 5.67},
            {"symbol": "ARM", "price": 152.30, "change_pct": 4.21},
        ],
        "losers": [
            {"symbol": "INTC", "price": 42.15, "change_pct": -3.82},
            {"symbol": "BA", "price": 178.90, "change_pct": -2.95},
            {"symbol": "PFE", "price": 26.40, "change_pct": -2.11},
        ],
    }


@router.get("/news")
async def get_market_news():
    """Return recent market news headlines."""
    return {
        "articles": [
            {
                "title": "Fed Signals Patience on Rate Cuts Amid Sticky Inflation",
                "source": "Reuters",
                "timestamp": "2026-03-03T14:30:00Z",
                "url": "https://example.com/news/1",
            },
            {
                "title": "Tech Earnings Beat Expectations Across the Board",
                "source": "Bloomberg",
                "timestamp": "2026-03-03T12:15:00Z",
                "url": "https://example.com/news/2",
            },
            {
                "title": "Oil Prices Drop on Surprise Inventory Build",
                "source": "CNBC",
                "timestamp": "2026-03-03T10:45:00Z",
                "url": "https://example.com/news/3",
            },
            {
                "title": "Semiconductor Stocks Rally on AI Demand Forecast",
                "source": "MarketWatch",
                "timestamp": "2026-03-03T09:20:00Z",
                "url": "https://example.com/news/4",
            },
        ]
    }


@router.get("/watchlist")
async def get_watchlist():
    """Return user watchlist items with current prices."""
    return {
        "items": [
            {"symbol": "AAPL", "name": "Apple Inc", "price": 178.50, "change": 1.23, "change_pct": 0.69},
            {"symbol": "MSFT", "name": "Microsoft Corp", "price": 415.80, "change": 3.45, "change_pct": 0.84},
            {"symbol": "GOOGL", "name": "Alphabet Inc", "price": 153.20, "change": -0.80, "change_pct": -0.52},
            {"symbol": "AMZN", "name": "Amazon.com Inc", "price": 182.90, "change": 2.10, "change_pct": 1.16},
            {"symbol": "TSLA", "name": "Tesla Inc", "price": 201.40, "change": -3.60, "change_pct": -1.76},
        ]
    }
