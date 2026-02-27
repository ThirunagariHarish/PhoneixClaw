import json
import logging
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from shared.models.database import get_session
from shared.models.trade import DataSource, StrategyModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])

STRATEGY_AGENT_URL = "http://strategy-agent:8025"


class StrategyCreate(BaseModel):
    name: str
    strategy_text: str
    ticker: str = "SPY"


class BacktestRequest(BaseModel):
    strategy_id: str | None = None
    strategy_text: str | None = None
    ticker: str = "SPY"
    period_years: int = 2


@router.get("")
async def list_strategies(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(StrategyModel)
        .where(StrategyModel.user_id == uuid.UUID(user_id))
        .order_by(desc(StrategyModel.updated_at))
    )
    return [_response(s) for s in result.scalars().all()]


@router.post("", status_code=201)
async def create_strategy(
    req: StrategyCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    strategy = StrategyModel(
        user_id=uuid.UUID(user_id),
        name=req.name,
        strategy_text=req.strategy_text,
    )
    session.add(strategy)
    await session.commit()
    await session.refresh(strategy)
    return _response(strategy)


@router.get("/{strategy_id}")
async def get_strategy(
    strategy_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    s = await _get_strategy(strategy_id, request, session)
    return _response(s)


@router.delete("/{strategy_id}", status_code=204)
async def delete_strategy(
    strategy_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    s = await _get_strategy(strategy_id, request, session)
    await session.delete(s)
    await session.commit()


@router.post("/{strategy_id}/parse")
async def parse_strategy(
    strategy_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    s = await _get_strategy(strategy_id, request, session)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{STRATEGY_AGENT_URL}/parse",
                json={"strategy_text": s.strategy_text},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Strategy agent unavailable: {str(e)[:200]}")

    s.parsed_config = data.get("parsed_config", {})
    s.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(s)
    return _response(s)


@router.post("/backtest")
async def run_backtest(
    req: BacktestRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    strategy_text = req.strategy_text
    parsed_config = {}

    if req.strategy_id:
        s = await _get_strategy(req.strategy_id, request, session)
        strategy_text = s.strategy_text
        parsed_config = s.parsed_config or {}

    if not strategy_text:
        raise HTTPException(status_code=400, detail="Strategy text required")

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{STRATEGY_AGENT_URL}/backtest",
                json={
                    "strategy_text": strategy_text,
                    "parsed_config": parsed_config,
                    "ticker": req.ticker,
                    "period_years": req.period_years,
                },
            )
            resp.raise_for_status()
            result = resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Backtest timed out")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Strategy agent error: {str(e)[:200]}")

    if req.strategy_id:
        s.backtest_summary = result.get("report", {})
        s.parsed_config = result.get("parsed_config", parsed_config)
        s.status = "backtested"
        s.updated_at = datetime.now(timezone.utc)
        await session.commit()

    return result


@router.post("/{strategy_id}/deploy")
async def deploy_strategy(
    strategy_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    s = await _get_strategy(strategy_id, request, session)
    if not s.backtest_summary:
        raise HTTPException(status_code=400, detail="Run backtest before deploying")

    s.status = "deployed"
    s.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(s)
    return _response(s)


# ── Deploy strategy as a signal data source ───────────────────────────────────

@router.post("/{strategy_id}/deploy-as-source")
async def deploy_as_source(
    strategy_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Deploy a backtested strategy as a signal data source."""
    s = await _get_strategy(strategy_id, request, session)
    if not s.backtest_summary:
        raise HTTPException(status_code=400, detail="Run backtest before deploying as source")

    existing = await session.execute(
        select(DataSource).where(
            DataSource.linked_strategy_id == s.id,
            DataSource.user_id == uuid.UUID(request.state.user_id),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Strategy is already deployed as a data source")

    ds = DataSource(
        user_id=uuid.UUID(request.state.user_id),
        source_type="strategy",
        display_name=f"Strategy: {s.name}",
        auth_type="none",
        credentials_encrypted=b"",
        data_purpose="trades",
        connection_status="CONNECTED",
        linked_strategy_id=s.id,
    )
    session.add(ds)

    s.status = "deployed"
    s.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(ds)
    await session.refresh(s)

    return {
        "strategy": _response(s),
        "data_source": {
            "id": str(ds.id),
            "display_name": ds.display_name,
            "source_type": ds.source_type,
        },
    }


# ── Approval endpoint for agent deploy gates ─────────────────────────────────

class ApprovalRequest(BaseModel):
    strategy_id: str
    approved: bool


@router.post("/agent/approve")
async def agent_approve_action(
    req: ApprovalRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Handle user approval/rejection for high-risk agent actions like deploy."""
    if not req.approved:
        return {"status": "rejected", "message": "Deployment cancelled by user."}

    s = await _get_strategy(req.strategy_id, request, session)
    if not s.backtest_summary:
        raise HTTPException(status_code=400, detail="Strategy must be backtested before deployment")

    s.status = "deployed"
    s.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(s)
    return {"status": "approved", "message": "Strategy deployed successfully.", "strategy": _response(s)}


# ── Agent Chat (non-streaming) ───────────────────────────────────────────────

class AgentChatRequest(BaseModel):
    message: str
    conversation_history: list[dict] = []
    strategy_context: dict | None = None


@router.post("/agent/chat")
async def agent_chat(
    req: AgentChatRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Proxy to the strategy agent's ReAct chat endpoint."""
    user_id = request.state.user_id
    strategy_context = await _build_strategy_context(req, user_id, session)

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{STRATEGY_AGENT_URL}/agent/chat",
                json={
                    "message": req.message,
                    "conversation_history": req.conversation_history,
                    "strategy_context": strategy_context,
                    "user_id": user_id,
                },
            )
            resp.raise_for_status()
            agent_response = resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Agent timed out")
    except Exception as e:
        logger.warning("Agent unavailable: %s", e)
        agent_response = {
            "message": _fallback_response(req.message),
            "steps": [{"type": "response", "content": _fallback_response(req.message)}],
        }

    await _persist_agent_results(agent_response, user_id, strategy_context, request, session)
    return agent_response


# ── Agent Chat (SSE streaming) ───────────────────────────────────────────────

@router.post("/agent/chat/stream")
async def agent_chat_stream(
    req: AgentChatRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """SSE streaming proxy — forwards events from the strategy agent to the frontend."""
    user_id = request.state.user_id
    strategy_context = await _build_strategy_context(req, user_id, session)

    async def generate():
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream(
                    "POST",
                    f"{STRATEGY_AGENT_URL}/agent/chat/stream",
                    json={
                        "message": req.message,
                        "conversation_history": req.conversation_history,
                        "strategy_context": strategy_context,
                        "user_id": user_id,
                    },
                ) as resp:
                    collected_steps = []
                    final_message = ""
                    async for line in resp.aiter_lines():
                        if line.startswith("data: "):
                            yield line + "\n\n"
                            try:
                                data = json.loads(line[6:])
                                if data.get("type") == "done":
                                    final_message = data.get("message", "")
                                else:
                                    collected_steps.append(data)
                            except Exception:
                                pass

                    await _persist_agent_results(
                        {"steps": collected_steps, "message": final_message},
                        user_id, strategy_context, request, session,
                    )
        except Exception as e:
            logger.warning("SSE stream error: %s", e)
            fallback = _fallback_response(req.message)
            yield f"data: {json.dumps({'type': 'response', 'content': fallback})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'message': fallback})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _build_strategy_context(
    req: AgentChatRequest, user_id: str, session: AsyncSession
) -> dict:
    strategy_context = req.strategy_context or {}
    if not strategy_context.get("strategies"):
        result = await session.execute(
            select(StrategyModel)
            .where(StrategyModel.user_id == uuid.UUID(user_id))
            .order_by(desc(StrategyModel.updated_at))
            .limit(5)
        )
        existing = result.scalars().all()
        strategy_context["strategies"] = [
            {"id": str(s.id), "name": s.name, "status": s.status, "text": s.strategy_text[:100]}
            for s in existing
        ]
    return strategy_context


async def _persist_agent_results(
    agent_response: dict,
    user_id: str,
    strategy_context: dict,
    request: Request,
    session: AsyncSession,
):
    """Persist strategy creation and backtest results from agent steps."""
    for step in agent_response.get("steps", []):
        if step.get("tool") == "create_strategy" and step.get("status") == "success":
            result_data = step.get("result", {})
            if result_data.get("name"):
                strategy = StrategyModel(
                    user_id=uuid.UUID(user_id),
                    name=result_data["name"],
                    strategy_text=result_data.get("strategy_text", ""),
                )
                session.add(strategy)
                await session.commit()
                await session.refresh(strategy)
                step["result"]["id"] = str(strategy.id)

        if step.get("tool") == "backtest" and step.get("status") == "success":
            report = step.get("result", {}).get("report")
            if report and strategy_context.get("active_strategy_id"):
                try:
                    s = await _get_strategy(strategy_context["active_strategy_id"], request, session)
                    s.backtest_summary = report
                    s.status = "backtested"
                    s.updated_at = datetime.now(timezone.utc)
                    await session.commit()
                except Exception:
                    pass


def _fallback_response(message: str) -> str:
    msg_lower = message.lower()
    if any(w in msg_lower for w in ["create", "build", "make", "new"]):
        return ("I'd love to help you create a strategy! The AI agent service is currently "
                "starting up. Please try again in a moment. In the meantime, you can describe "
                "your strategy idea in detail — include the asset, entry/exit rules, and any "
                "time constraints.")
    if any(w in msg_lower for w in ["backtest", "test", "run"]):
        return ("I'll run that backtest for you as soon as the agent service is ready. "
                "Please try again in a few seconds.")
    return ("I'm your autonomous strategy agent. I can create, backtest, and deploy trading "
            "strategies from natural language. The AI service is warming up — please try again shortly.")


async def _get_strategy(strategy_id: str, request: Request, session: AsyncSession) -> StrategyModel:
    user_id = request.state.user_id
    result = await session.execute(
        select(StrategyModel).where(
            StrategyModel.id == uuid.UUID(strategy_id),
            StrategyModel.user_id == uuid.UUID(user_id),
        )
    )
    s = result.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return s


def _response(s: StrategyModel) -> dict:
    return {
        "id": str(s.id),
        "name": s.name,
        "strategy_text": s.strategy_text,
        "parsed_config": s.parsed_config or {},
        "features": s.features or [],
        "backtest_summary": s.backtest_summary,
        "status": s.status,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }
