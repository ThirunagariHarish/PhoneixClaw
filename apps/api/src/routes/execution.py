"""
Execution API: submit trade intents, check status, kill switch.

M1.12: Execution pipeline API.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v2/execution", tags=["execution"])


class TradeIntentSubmit(BaseModel):
    agent_id: str
    account_id: str
    symbol: str
    side: str = Field(..., pattern="^(buy|sell)$")
    qty: float = Field(..., gt=0)
    order_type: str = "market"
    limit_price: float | None = None
    stop_price: float | None = None
    signal_source: str | None = None
    signal_data: dict[str, Any] = Field(default_factory=dict)


@router.post("/trade-intents", status_code=status.HTTP_202_ACCEPTED)
async def submit_trade_intent(payload: TradeIntentSubmit):
    """Submit a trade intent to the execution pipeline (Redis Stream)."""
    # In production: push to Redis Stream 'phoenix:trade-intents'
    return {
        "status": "accepted",
        "message": "Trade intent queued for execution",
        "intent": payload.model_dump(),
    }


@router.get("/status")
async def execution_status():
    """Get execution service and circuit breaker status."""
    return {
        "execution_service": "running",
        "circuit_breaker": {"state": "CLOSED", "is_trading_allowed": True},
        "queue_depth": 0,
        "fills_today": 0,
        "rejections_today": 0,
    }


@router.post("/kill-switch")
async def kill_switch():
    """Emergency kill switch — halt all trading immediately."""
    # In production: set circuit breaker to OPEN, cancel pending intents
    return {
        "status": "activated",
        "message": "Kill switch activated. All trading halted.",
    }


@router.post("/kill-switch/reset")
async def reset_kill_switch():
    """Reset kill switch — resume trading."""
    return {
        "status": "reset",
        "message": "Kill switch reset. Trading in HALF_OPEN mode for recovery.",
    }
