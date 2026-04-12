"""
Macro-Pulse API routes: regime, calendar, indicators.

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
    """Upcoming economic calendar: FOMC, CPI, NFP, GDP."""
    return await _fetcher.get_calendar(limit=limit)


@router.get("/indicators")
async def get_indicators():
    """Live macro indicators: VIX, 10Y, DXY, gold, oil, SPY, QQQ, BTC."""
    return await _fetcher.get_indicators()


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
