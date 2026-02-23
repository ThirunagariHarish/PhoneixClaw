import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.database import get_session
from shared.models.trade import (
    AccountSourceMapping,
    Channel,
    DataSource,
    TradePipeline,
    TradingAccount,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/pipelines", tags=["pipelines"])


class PipelineCreate(BaseModel):
    name: str
    data_source_id: str
    channel_id: str
    trading_account_id: str
    auto_approve: bool = True
    paper_mode: bool = False


class PipelineUpdate(BaseModel):
    name: str | None = None
    auto_approve: bool | None = None
    paper_mode: bool | None = None


class PipelineResponse(BaseModel):
    id: str
    name: str
    data_source_id: str
    data_source_name: str | None = None
    channel_id: str
    channel_name: str | None = None
    channel_identifier: str | None = None
    trading_account_id: str
    trading_account_name: str | None = None
    enabled: bool
    status: str
    error_message: str | None = None
    auto_approve: bool
    paper_mode: bool
    last_message_at: str | None = None
    messages_count: int
    trades_count: int
    created_at: str
    updated_at: str


def _pipeline_response(p: TradePipeline) -> PipelineResponse:
    return PipelineResponse(
        id=str(p.id),
        name=p.name,
        data_source_id=str(p.data_source_id),
        data_source_name=p.data_source.display_name if p.data_source else None,
        channel_id=str(p.channel_id),
        channel_name=p.channel.display_name if p.channel else None,
        channel_identifier=p.channel.channel_identifier if p.channel else None,
        trading_account_id=str(p.trading_account_id),
        trading_account_name=p.trading_account.display_name if p.trading_account else None,
        enabled=p.enabled,
        status=p.status,
        error_message=p.error_message,
        auto_approve=p.auto_approve,
        paper_mode=p.paper_mode,
        last_message_at=p.last_message_at.isoformat() if p.last_message_at else None,
        messages_count=p.messages_count or 0,
        trades_count=p.trades_count or 0,
        created_at=p.created_at.isoformat() if p.created_at else "",
        updated_at=p.updated_at.isoformat() if p.updated_at else "",
    )


def _safe_uuid(val: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(val)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Invalid UUID for {field}: {val}")


@router.get("", response_model=list[PipelineResponse])
async def list_pipelines(
    request: Request,
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    is_admin = getattr(request.state, "is_admin", False)

    stmt = select(TradePipeline).options(
    ).order_by(desc(TradePipeline.created_at)).limit(limit).offset(offset)

    if not is_admin:
        stmt = stmt.where(TradePipeline.user_id == uuid.UUID(user_id))

    result = await session.execute(stmt)
    pipelines = result.scalars().all()

    for p in pipelines:
        await session.refresh(p, ["data_source", "channel", "trading_account"])

    return [_pipeline_response(p) for p in pipelines]


@router.post("", response_model=PipelineResponse, status_code=201)
async def create_pipeline(
    req: PipelineCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    uid = uuid.UUID(user_id)

    ds_id = _safe_uuid(req.data_source_id, "data_source_id")
    ch_id = _safe_uuid(req.channel_id, "channel_id")
    ta_id = _safe_uuid(req.trading_account_id, "trading_account_id")

    source = await session.get(DataSource, ds_id)
    if not source or source.user_id != uid:
        raise HTTPException(status_code=404, detail="Data source not found")

    channel = await session.get(Channel, ch_id)
    if not channel or channel.data_source_id != ds_id:
        raise HTTPException(status_code=404, detail="Channel not found for this data source")

    account = await session.get(TradingAccount, ta_id)
    if not account or account.user_id != uid:
        raise HTTPException(status_code=404, detail="Trading account not found")

    existing = await session.execute(
        select(TradePipeline).where(
            TradePipeline.channel_id == ch_id,
            TradePipeline.trading_account_id == ta_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="A pipeline already exists for this channel and trading account",
        )

    pipeline = TradePipeline(
        user_id=uid,
        name=req.name,
        data_source_id=ds_id,
        channel_id=ch_id,
        trading_account_id=ta_id,
        auto_approve=req.auto_approve,
        paper_mode=req.paper_mode,
        enabled=True,
        status="STOPPED",
    )
    session.add(pipeline)

    mapping_exists = await session.execute(
        select(AccountSourceMapping).where(
            AccountSourceMapping.channel_id == ch_id,
            AccountSourceMapping.trading_account_id == ta_id,
        )
    )
    if not mapping_exists.scalar_one_or_none():
        mapping = AccountSourceMapping(
            trading_account_id=ta_id,
            channel_id=ch_id,
            enabled=True,
        )
        session.add(mapping)

    await session.commit()
    await session.refresh(pipeline, ["data_source", "channel", "trading_account"])
    return _pipeline_response(pipeline)


@router.get("/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    p_id = _safe_uuid(pipeline_id, "pipeline_id")

    pipeline = await session.get(TradePipeline, p_id)
    if not pipeline or str(pipeline.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    await session.refresh(pipeline, ["data_source", "channel", "trading_account"])
    return _pipeline_response(pipeline)


@router.put("/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline(
    pipeline_id: str,
    req: PipelineUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    p_id = _safe_uuid(pipeline_id, "pipeline_id")

    pipeline = await session.get(TradePipeline, p_id)
    if not pipeline or str(pipeline.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    if req.name is not None:
        pipeline.name = req.name
    if req.auto_approve is not None:
        pipeline.auto_approve = req.auto_approve
    if req.paper_mode is not None:
        pipeline.paper_mode = req.paper_mode
    pipeline.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(pipeline, ["data_source", "channel", "trading_account"])
    return _pipeline_response(pipeline)


@router.delete("/{pipeline_id}", status_code=204)
async def delete_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    p_id = _safe_uuid(pipeline_id, "pipeline_id")

    pipeline = await session.get(TradePipeline, p_id)
    if not pipeline or str(pipeline.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    await session.delete(pipeline)
    await session.commit()


@router.post("/{pipeline_id}/start", response_model=PipelineResponse)
async def start_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    p_id = _safe_uuid(pipeline_id, "pipeline_id")

    pipeline = await session.get(TradePipeline, p_id)
    if not pipeline or str(pipeline.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    pipeline.enabled = True
    pipeline.status = "STOPPED"
    pipeline.error_message = None
    pipeline.updated_at = datetime.now(timezone.utc)

    source = await session.get(DataSource, pipeline.data_source_id)
    if source and not source.enabled:
        source.enabled = True
        source.updated_at = datetime.now(timezone.utc)

    await session.commit()
    await session.refresh(pipeline, ["data_source", "channel", "trading_account"])
    return _pipeline_response(pipeline)


@router.post("/{pipeline_id}/stop", response_model=PipelineResponse)
async def stop_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    p_id = _safe_uuid(pipeline_id, "pipeline_id")

    pipeline = await session.get(TradePipeline, p_id)
    if not pipeline or str(pipeline.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    pipeline.enabled = False
    pipeline.status = "STOPPED"
    pipeline.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(pipeline, ["data_source", "channel", "trading_account"])
    return _pipeline_response(pipeline)
