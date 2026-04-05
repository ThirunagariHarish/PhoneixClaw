"""
Daily Signals API routes: list signals, pipeline status, deploy pipeline, signal detail.

Phoenix v2 — 3-agent pipeline (Research → Technical → Risk).
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/api/v2/daily-signals", tags=["daily-signals"])


class SignalResponse(BaseModel):
    id: str
    time: str
    symbol: str
    direction: str
    confidence: float
    source_agent: str
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    status: str
    research_note: str | None = None
    technical_chart_ref: str | None = None
    risk_analysis: str | None = None


class PipelineAgentResponse(BaseModel):
    id: str
    name: str
    status: str
    last_run: str
    signals_produced: int


class PipelineStatusResponse(BaseModel):
    status: str
    instance_id: str | None
    agents: list[PipelineAgentResponse]


class DeployPayload(BaseModel):
    instance_id: str


@router.get("", response_model=list[SignalResponse])
async def list_signals() -> list[SignalResponse]:
    """List today's daily signals."""
    return []


@router.get("/pipeline", response_model=PipelineStatusResponse)
async def get_pipeline_status() -> PipelineStatusResponse:
    """Get pipeline status and agent states."""
    return PipelineStatusResponse(status="not_deployed", instance_id=None, agents=[])


@router.post("/pipeline/deploy")
async def deploy_pipeline(payload: DeployPayload) -> dict:
    """Deploy 3-agent pipeline to specified instance."""
    return {"status": "deployed", "instance_id": payload.instance_id, "message": "Pipeline deployed"}


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal_detail(signal_id: str) -> SignalResponse:
    """Get signal detail with research note, technical ref, risk analysis."""
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signal not found")
