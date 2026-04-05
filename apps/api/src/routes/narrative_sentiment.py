"""
Narrative Sentinel API routes: sentiment feed, fed-watch, social, earnings, analyst-moves, agent create.

Phoenix v2 — NLP-powered sentiment intelligence from the Narrative Sentinel agent.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/v2/narrative", tags=["narrative-sentiment"])


class CreateAgentPayload(BaseModel):
    instance_id: str


@router.get("/feed")
async def get_feed() -> dict:
    """Sentiment feed with scored headlines and metrics."""
    return {"items": [], "metrics": {"marketSentiment": 0, "fearGreed": 0, "twitterVelocity": 0, "newsSentimentAvg": 0}}


@router.get("/fed-watch")
async def get_fed_watch() -> list:
    """Upcoming Fed speakers and transcript summaries."""
    return []


@router.get("/social")
async def get_social() -> dict:
    """Social pulse: cashtags, WSB momentum, sentiment heatmap."""
    return {"cashtags": [], "wsbMomentum": [], "heatmap": []}


@router.get("/earnings")
async def get_earnings() -> list:
    """Earnings intelligence with sentiment expectation and post-earnings risk."""
    return []


@router.get("/analyst-moves")
async def get_analyst_moves() -> list:
    """Recent analyst upgrades/downgrades with expected price impact."""
    return []


@router.post("/agent/create")
async def create_agent(payload: CreateAgentPayload) -> dict:
    """Deploy sentiment agent on specified instance."""
    return {"status": "created", "instance_id": payload.instance_id, "message": "Sentiment agent deployed"}
