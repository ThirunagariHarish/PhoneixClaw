"""
Risk Guardian API routes: status, position-limits, checks, compliance, hedging, agent create, circuit-breaker reset.

Phoenix v2 — Real-time risk monitoring from the Risk Guardian agent.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v2/risk", tags=["risk-compliance"])


class CreateAgentPayload(BaseModel):
    instance_id: str


@router.get("/status")
async def get_status() -> dict:
    """Overall risk status and circuit breaker state."""
    return {
        "var": 0,
        "dailyPnlPct": 0,
        "marginUsagePct": 0,
        "circuitBreaker": "NORMAL",
        "circuit": {
            "state": "NORMAL",
            "dailyLossPct": 0,
            "thresholdPct": -5,
            "confidence": 0,
            "consecutiveLosses": 0,
        },
    }


@router.get("/position-limits")
async def get_position_limits() -> dict:
    """Sector and ticker exposure vs limits."""
    return {"sectors": [], "tickerConcentration": [], "marginUsagePct": 0}


@router.get("/checks")
async def get_checks() -> list:
    """Recent risk check log."""
    return []


@router.get("/compliance")
async def get_compliance() -> list:
    """Compliance alerts: wash sale, PDT, agent conflict."""
    return []


@router.get("/hedging")
async def get_hedging() -> dict:
    """Hedge status: black swan, protective puts, beta."""
    return {"blackSwanStatus": "INACTIVE", "protectivePuts": [], "hedgeCostPct": 0, "portfolioBeta": 0}


@router.post("/agent/create")
async def create_agent(payload: CreateAgentPayload) -> dict:
    """Deploy Risk Guardian agent on specified instance."""
    return {"status": "created", "instance_id": payload.instance_id, "message": "Risk Guardian deployed"}


@router.post("/circuit-breaker/reset")
async def reset_circuit_breaker() -> dict:
    """Manual reset of circuit breaker."""
    return {"status": "reset", "message": "Circuit breaker reset"}
