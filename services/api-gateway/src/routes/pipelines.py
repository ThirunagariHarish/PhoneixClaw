import asyncio
import logging
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.crypto.credentials import encrypt_credentials
from shared.models.database import get_session
from shared.models.trade import (
    AITradeDecision,
    AccountSourceMapping,
    Channel,
    DataSource,
    RawMessage,
    Trade,
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
    pipeline_type: str = "trade"
    trigger_config: dict = {}
    market_hours_mode: str = "regular_only"


class PipelineUpdate(BaseModel):
    name: str | None = None
    trading_account_id: str | None = None
    auto_approve: bool | None = None
    paper_mode: bool | None = None
    pipeline_type: str | None = None
    trigger_config: dict | None = None
    market_hours_mode: str | None = None


class ChatPipelineCreate(BaseModel):
    name: str
    trading_account_id: str
    auto_approve: bool = True
    paper_mode: bool = False


class PipelineResponse(BaseModel):
    id: str
    name: str
    data_source_id: str
    data_source_name: str | None = None
    source_type: str | None = None
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
    pipeline_type: str = "trade"
    trigger_config: dict = {}
    market_hours_mode: str = "regular_only"
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
        source_type=p.data_source.source_type if p.data_source else None,
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
        pipeline_type=p.pipeline_type or "trade",
        trigger_config=p.trigger_config or {},
        market_hours_mode=p.market_hours_mode or "regular_only",
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


async def _get_pipeline(
    pipeline_id: str, request: Request, session: AsyncSession,
) -> TradePipeline:
    p_id = _safe_uuid(pipeline_id, "pipeline_id")
    pipeline = await session.get(TradePipeline, p_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin and str(pipeline.user_id) != request.state.user_id:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline


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

    is_admin = getattr(request.state, "is_admin", False)

    source = await session.get(DataSource, ds_id)
    if not source or (not is_admin and source.user_id != uid):
        raise HTTPException(status_code=404, detail="Data source not found")

    channel = await session.get(Channel, ch_id)
    if not channel or channel.data_source_id != ds_id:
        raise HTTPException(status_code=404, detail="Channel not found for this data source")

    account = await session.get(TradingAccount, ta_id)
    if not account or (not is_admin and account.user_id != uid):
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
        pipeline_type=req.pipeline_type,
        trigger_config=req.trigger_config,
        market_hours_mode=req.market_hours_mode,
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


@router.post("/chat", response_model=PipelineResponse, status_code=201)
async def create_chat_pipeline(
    req: ChatPipelineCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    uid = uuid.UUID(user_id)
    ta_id = _safe_uuid(req.trading_account_id, "trading_account_id")

    account = await session.get(TradingAccount, ta_id)
    is_admin = getattr(request.state, "is_admin", False)
    if not account or (not is_admin and account.user_id != uid):
        raise HTTPException(status_code=404, detail="Trading account not found")

    existing_ds = await session.execute(
        select(DataSource).where(
            DataSource.user_id == uid,
            DataSource.source_type == "chat",
        ).limit(1)
    )
    ds = existing_ds.scalar_one_or_none()
    if not ds:
        ds = DataSource(
            user_id=uid,
            source_type="chat",
            display_name="Chat Widget",
            auth_type="none",
            credentials_encrypted=encrypt_credentials({}),
            connection_status="CONNECTED",
        )
        session.add(ds)
        await session.flush()

    existing_ch = await session.execute(
        select(Channel).where(
            Channel.data_source_id == ds.id,
            Channel.channel_identifier == "chat-widget",
        ).limit(1)
    )
    ch = existing_ch.scalar_one_or_none()
    if not ch:
        ch = Channel(
            data_source_id=ds.id,
            channel_identifier="chat-widget",
            display_name="Chat Widget",
        )
        session.add(ch)
        await session.flush()

    dup = await session.execute(
        select(TradePipeline).where(
            TradePipeline.channel_id == ch.id,
            TradePipeline.trading_account_id == ta_id,
        )
    )
    if dup.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="A chat pipeline already exists for this trading account",
        )

    pipeline = TradePipeline(
        user_id=uid,
        name=req.name,
        data_source_id=ds.id,
        channel_id=ch.id,
        trading_account_id=ta_id,
        auto_approve=req.auto_approve,
        paper_mode=req.paper_mode,
        enabled=True,
        status="CONNECTED",
    )
    session.add(pipeline)

    mapping_exists = await session.execute(
        select(AccountSourceMapping).where(
            AccountSourceMapping.channel_id == ch.id,
            AccountSourceMapping.trading_account_id == ta_id,
        )
    )
    if not mapping_exists.scalar_one_or_none():
        session.add(AccountSourceMapping(
            trading_account_id=ta_id,
            channel_id=ch.id,
            enabled=True,
        ))

    await session.commit()
    await session.refresh(pipeline, ["data_source", "channel", "trading_account"])
    return _pipeline_response(pipeline)


@router.get("/diagnostics")
async def pipeline_diagnostics(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Admin-only endpoint that checks all pipeline infrastructure health."""
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin only")

    results: dict = {}

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            resp = await client.get("http://source-orchestrator:8002/debug/workers")
            results["orchestrator"] = resp.json()
        except Exception as e:
            results["orchestrator"] = {"error": str(e), "status": "unreachable"}

        try:
            resp = await client.get("http://audit-writer:8012/health")
            results["audit_writer"] = resp.json()
        except Exception as e:
            results["audit_writer"] = {"error": str(e), "status": "unreachable"}

        for svc_name, svc_port in [
            ("trade_parser", 8006), ("trade_gateway", 8007), ("trade_executor", 8008),
        ]:
            try:
                resp = await client.get(f"http://{svc_name.replace('_', '-')}:{svc_port}/health")
                results[svc_name] = resp.json()
            except Exception as e:
                results[svc_name] = {"error": str(e), "status": "unreachable"}

    try:
        from shared.kafka_utils.producer import KafkaProducerWrapper
        p = KafkaProducerWrapper()
        await p.start()
        await p.stop()
        results["kafka"] = {"status": "reachable"}
    except Exception as e:
        results["kafka"] = {"status": "unreachable", "error": str(e)}

    total_count = (await session.execute(
        select(func.count(RawMessage.id))
    )).scalar() or 0
    recent_result = await session.execute(
        select(RawMessage).order_by(desc(RawMessage.created_at)).limit(5)
    )
    recent_msgs = recent_result.scalars().all()
    results["raw_messages"] = {
        "total_count": total_count,
        "recent": [
            {
                "id": str(m.id),
                "content": (m.content or "")[:80],
                "channel_name": m.channel_name,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in recent_msgs
        ],
    }

    pipeline_count = (await session.execute(
        select(func.count(TradePipeline.id))
    )).scalar() or 0
    enabled_count = (await session.execute(
        select(func.count(TradePipeline.id)).where(TradePipeline.enabled.is_(True))
    )).scalar() or 0
    results["pipelines"] = {
        "total": pipeline_count,
        "enabled": enabled_count,
    }

    return results


@router.post("/{pipeline_id}/test")
async def test_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Admin-only: publish a test message through the pipeline and verify it reaches the DB."""
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin only")

    pipeline = await _get_pipeline(pipeline_id, request, session)
    await session.refresh(pipeline, ["data_source", "channel"])

    test_id = f"test-{uuid.uuid4().hex[:12]}"
    test_content = f"[PIPELINE TEST] {test_id}"

    from shared.kafka_utils.producer import KafkaProducerWrapper
    producer = KafkaProducerWrapper()
    try:
        await producer.start()
        raw_msg = {
            "content": test_content,
            "message_id": test_id,
            "source_message_id": test_id,
            "author": "pipeline-test",
            "channel_name": pipeline.channel.display_name if pipeline.channel else "test",
            "channel_id": pipeline.channel.channel_identifier if pipeline.channel else "",
            "guild_id": "",
            "user_id": str(pipeline.user_id),
            "data_source_id": str(pipeline.data_source_id),
            "pipeline_id": str(pipeline.id),
            "source": "test",
            "source_type": "test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        headers = [
            ("user_id", str(pipeline.user_id).encode("utf-8")),
            ("pipeline_id", str(pipeline.id).encode("utf-8")),
        ]
        await producer.send_and_wait("raw-messages", value=raw_msg, key=test_id, headers=headers)
        kafka_ok = True
    except Exception as e:
        logger.exception("Test message Kafka publish failed")
        return {"success": False, "stage": "kafka_publish", "error": str(e)}
    finally:
        await producer.stop()

    if not kafka_ok:
        return {"success": False, "stage": "kafka_publish"}

    for i in range(20):
        await asyncio.sleep(0.5)
        result = await session.execute(
            select(RawMessage).where(RawMessage.source_message_id == test_id)
        )
        found = result.scalar_one_or_none()
        if found:
            return {
                "success": True,
                "latency_seconds": round((i + 1) * 0.5, 1),
                "message_id": str(found.id),
                "stage": "complete",
            }

    return {
        "success": False,
        "stage": "db_write",
        "detail": "Message reached Kafka but did not appear in DB within 10s. Audit-writer may be down.",
    }


@router.post("/{pipeline_id}/test-trade")
async def test_trade_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Admin-only: simulate a full trade flow through the pipeline.

    Publishes a realistic BTO message to Kafka, then tracks it
    through parsing, gateway approval, and (if paper mode) execution.
    Returns status at each stage.
    """
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin only")

    pipeline = await _get_pipeline(pipeline_id, request, session)
    await session.refresh(pipeline, ["data_source", "channel", "trading_account"])

    if not pipeline.trading_account:
        raise HTTPException(status_code=400, detail="Pipeline has no trading account")

    is_paper = pipeline.trading_account.paper_mode if pipeline.trading_account else True
    if not is_paper:
        raise HTTPException(
            status_code=400,
            detail="Trade test is only allowed on paper-mode accounts to avoid real money trades",
        )

    test_id = f"trade-test-{uuid.uuid4().hex[:12]}"
    trade_msg = "BTO SPY 600C 12/31 @ 0.01"
    test_content = f"[TRADE TEST {test_id}] {trade_msg}"

    stages: dict = {"test_id": test_id, "paper_mode": is_paper}

    from shared.kafka_utils.producer import KafkaProducerWrapper
    producer = KafkaProducerWrapper()
    try:
        await producer.start()
        raw_msg = {
            "content": test_content,
            "message_id": test_id,
            "source_message_id": test_id,
            "author": "trade-test",
            "channel_name": pipeline.channel.display_name if pipeline.channel else "test",
            "channel_id": pipeline.channel.channel_identifier if pipeline.channel else "",
            "guild_id": "",
            "user_id": str(pipeline.user_id),
            "data_source_id": str(pipeline.data_source_id),
            "pipeline_id": str(pipeline.id),
            "source": "test",
            "source_type": "test",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        headers = [
            ("user_id", str(pipeline.user_id).encode("utf-8")),
            ("pipeline_id", str(pipeline.id).encode("utf-8")),
        ]
        await producer.send_and_wait("raw-messages", value=raw_msg, key=test_id, headers=headers)
        stages["kafka_publish"] = "ok"
    except Exception as e:
        stages["kafka_publish"] = f"FAILED: {e}"
        return {"success": False, "stage": "kafka_publish", **stages}
    finally:
        await producer.stop()

    for i in range(20):
        await asyncio.sleep(0.5)
        result = await session.execute(
            select(RawMessage).where(RawMessage.source_message_id == test_id)
        )
        if result.scalar_one_or_none():
            stages["audit_writer"] = f"ok ({round((i + 1) * 0.5, 1)}s)"
            break
    else:
        stages["audit_writer"] = "FAILED: message not in DB after 10s"
        return {"success": False, "stage": "audit_writer", **stages}

    for i in range(30):
        await asyncio.sleep(0.5)
        result = await session.execute(
            select(Trade).where(Trade.source_message_id == test_id)
        )
        trade = result.scalar_one_or_none()
        if trade:
            stages["trade_parser"] = f"ok ({round((i + 1) * 0.5, 1)}s)"
            stages["trade_status"] = trade.status
            stages["trade_id"] = str(trade.trade_id)
            if trade.broker_order_id:
                stages["broker_order_id"] = trade.broker_order_id
            if trade.fill_price:
                stages["fill_price"] = float(trade.fill_price)
            if trade.error_message:
                stages["error_message"] = trade.error_message
            if trade.rejection_reason:
                stages["rejection_reason"] = trade.rejection_reason
            if trade.status in ("EXECUTED", "IN_PROGRESS", "PENDING", "REJECTED", "ERROR"):
                stages["trade_gateway"] = "ok"
            break
    else:
        stages["trade_parser"] = "FAILED: no trade record after 15s"
        return {"success": False, "stage": "trade_parser", **stages}

    if trade and trade.status in ("IN_PROGRESS", "PENDING"):
        for i in range(40):
            await asyncio.sleep(0.5)
            await session.refresh(trade)
            if trade.status not in ("IN_PROGRESS", "PENDING"):
                stages["trade_executor"] = f"ok ({round((i + 1) * 0.5, 1)}s)"
                stages["trade_status"] = trade.status
                if trade.broker_order_id:
                    stages["broker_order_id"] = trade.broker_order_id
                if trade.error_message:
                    stages["error_message"] = trade.error_message
                break
        else:
            stages["trade_executor"] = f"TIMEOUT: still {trade.status} after 20s"

    overall = all(
        v == "ok" or (isinstance(v, str) and v.startswith("ok"))
        for k, v in stages.items()
        if k in ("kafka_publish", "audit_writer", "trade_parser", "trade_gateway")
    )
    return {"success": overall, "stage": "complete", **stages}


@router.get("/{pipeline_id}", response_model=PipelineResponse)
async def get_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    pipeline = await _get_pipeline(pipeline_id, request, session)
    await session.refresh(pipeline, ["data_source", "channel", "trading_account"])
    return _pipeline_response(pipeline)


@router.get("/{pipeline_id}/trades")
async def pipeline_trades(
    pipeline_id: str,
    request: Request,
    status: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Get trades associated with this pipeline (matched via channel)."""
    pipeline = await _get_pipeline(pipeline_id, request, session)
    stmt = (
        select(Trade)
        .where(
            Trade.user_id == pipeline.user_id,
            Trade.channel_id == pipeline.channel_id,
        )
    )
    if status:
        stmt = stmt.where(Trade.status == status)
    stmt = stmt.order_by(desc(Trade.created_at)).limit(limit).offset(offset)
    result = await session.execute(stmt)
    trades = result.scalars().all()
    return [
        {
            "id": t.id,
            "trade_id": str(t.trade_id),
            "ticker": t.ticker,
            "strike": float(t.strike),
            "option_type": t.option_type,
            "action": t.action,
            "price": float(t.price),
            "quantity": t.quantity,
            "status": t.status,
            "source": t.source,
            "error_message": t.error_message,
            "rejection_reason": t.rejection_reason,
            "broker_order_id": t.broker_order_id,
            "raw_message": t.raw_message,
            "buffered_price": float(t.buffered_price) if t.buffered_price else None,
            "fill_price": float(t.fill_price) if t.fill_price else None,
            "realized_pnl": float(t.realized_pnl) if t.realized_pnl else None,
            "execution_latency_ms": t.execution_latency_ms,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "processed_at": t.processed_at.isoformat() if t.processed_at else None,
        }
        for t in trades
    ]


@router.get("/{pipeline_id}/stats")
async def pipeline_stats(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Aggregate stats for a single pipeline."""
    pipeline = await _get_pipeline(pipeline_id, request, session)
    base = select(func.count(Trade.id)).where(
        Trade.user_id == pipeline.user_id,
        Trade.channel_id == pipeline.channel_id,
    )
    total = (await session.execute(base)).scalar() or 0
    executed = (await session.execute(base.where(Trade.status == "EXECUTED"))).scalar() or 0
    rejected = (await session.execute(base.where(Trade.status == "REJECTED"))).scalar() or 0
    errored = (await session.execute(base.where(Trade.status == "ERROR"))).scalar() or 0
    pending = (await session.execute(base.where(Trade.status == "PENDING"))).scalar() or 0

    pnl_result = await session.execute(
        select(func.sum(Trade.realized_pnl)).where(
            Trade.user_id == pipeline.user_id,
            Trade.channel_id == pipeline.channel_id,
            Trade.realized_pnl.isnot(None),
        )
    )
    total_pnl = float(pnl_result.scalar() or 0)

    winning = (await session.execute(
        select(func.count(Trade.id)).where(
            Trade.user_id == pipeline.user_id,
            Trade.channel_id == pipeline.channel_id,
            Trade.realized_pnl > 0,
        )
    )).scalar() or 0

    losing = (await session.execute(
        select(func.count(Trade.id)).where(
            Trade.user_id == pipeline.user_id,
            Trade.channel_id == pipeline.channel_id,
            Trade.realized_pnl < 0,
        )
    )).scalar() or 0

    closed = winning + losing
    win_rate = (winning / closed * 100) if closed > 0 else 0

    avg_latency_result = await session.execute(
        select(func.avg(Trade.execution_latency_ms)).where(
            Trade.user_id == pipeline.user_id,
            Trade.channel_id == pipeline.channel_id,
            Trade.execution_latency_ms.isnot(None),
        )
    )
    avg_latency = avg_latency_result.scalar()

    return {
        "total": total,
        "executed": executed,
        "rejected": rejected,
        "errored": errored,
        "pending": pending,
        "total_pnl": total_pnl,
        "winning": winning,
        "losing": losing,
        "win_rate": round(win_rate, 1),
        "avg_execution_latency_ms": round(float(avg_latency)) if avg_latency else None,
        "messages_count": pipeline.messages_count or 0,
    }


@router.get("/{pipeline_id}/performance")
async def pipeline_performance(
    pipeline_id: str,
    request: Request,
    days: int = Query(30, le=90),
    session: AsyncSession = Depends(get_session),
):
    """Time-series performance data for charting."""
    from sqlalchemy import cast, Date as SQLDate
    pipeline = await _get_pipeline(pipeline_id, request, session)

    stmt = (
        select(
            cast(Trade.created_at, SQLDate).label("date"),
            func.count(Trade.id).label("trades"),
            func.sum(Trade.realized_pnl).label("pnl"),
            func.count(Trade.id).filter(Trade.status == "EXECUTED").label("executed"),
        )
        .where(
            Trade.user_id == pipeline.user_id,
            Trade.channel_id == pipeline.channel_id,
        )
        .group_by(cast(Trade.created_at, SQLDate))
        .order_by(cast(Trade.created_at, SQLDate))
        .limit(days)
    )
    result = await session.execute(stmt)
    rows = result.all()

    cumulative_pnl = 0.0
    data = []
    for row in rows:
        day_pnl = float(row.pnl or 0)
        cumulative_pnl += day_pnl
        data.append({
            "date": row.date.isoformat(),
            "trades": row.trades,
            "pnl": round(day_pnl, 2),
            "cumulative_pnl": round(cumulative_pnl, 2),
            "executed": row.executed,
        })
    return data


@router.get("/{pipeline_id}/messages")
async def pipeline_messages(
    pipeline_id: str,
    request: Request,
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Recent raw messages for this pipeline's channel."""
    pipeline = await _get_pipeline(pipeline_id, request, session)
    await session.refresh(pipeline, ["channel"])

    channel_identifier = pipeline.channel.channel_identifier if pipeline.channel else None
    if not channel_identifier:
        return []

    stmt = (
        select(RawMessage)
        .where(
            RawMessage.user_id == pipeline.user_id,
            RawMessage.data_source_id == pipeline.data_source_id,
        )
        .order_by(desc(RawMessage.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    messages = result.scalars().all()
    return [
        {
            "id": str(m.id),
            "content": m.content,
            "author": m.author,
            "channel_name": m.channel_name,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]


@router.put("/{pipeline_id}", response_model=PipelineResponse)
async def update_pipeline(
    pipeline_id: str,
    req: PipelineUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    pipeline = await _get_pipeline(pipeline_id, request, session)

    if req.name is not None:
        pipeline.name = req.name
    if req.auto_approve is not None:
        pipeline.auto_approve = req.auto_approve
    if req.paper_mode is not None:
        pipeline.paper_mode = req.paper_mode

    if req.trading_account_id is not None:
        new_ta_uuid = _safe_uuid(req.trading_account_id, "trading_account_id")
        ta = await session.get(TradingAccount, new_ta_uuid)
        if not ta or str(ta.user_id) != request.state.user_id:
            raise HTTPException(status_code=400, detail="Trading account not found")
        pipeline.trading_account_id = new_ta_uuid

        old_mapping = await session.execute(
            select(AccountSourceMapping).where(
                AccountSourceMapping.channel_id == pipeline.channel_id,
                AccountSourceMapping.trading_account_id != new_ta_uuid,
            )
        )
        for m in old_mapping.scalars().all():
            await session.delete(m)

        existing = await session.execute(
            select(AccountSourceMapping).where(
                AccountSourceMapping.channel_id == pipeline.channel_id,
                AccountSourceMapping.trading_account_id == new_ta_uuid,
            )
        )
        if not existing.scalar_one_or_none():
            session.add(AccountSourceMapping(
                trading_account_id=new_ta_uuid,
                channel_id=pipeline.channel_id,
            ))

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
    pipeline = await _get_pipeline(pipeline_id, request, session)
    await session.delete(pipeline)
    await session.commit()


@router.post("/{pipeline_id}/start", response_model=PipelineResponse)
async def start_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    pipeline = await _get_pipeline(pipeline_id, request, session)

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
    pipeline = await _get_pipeline(pipeline_id, request, session)

    pipeline.enabled = False
    pipeline.status = "STOPPED"
    pipeline.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(pipeline, ["data_source", "channel", "trading_account"])
    return _pipeline_response(pipeline)


ai_router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


@ai_router.get("/decisions")
async def list_ai_decisions(
    request: Request,
    ticker: str | None = Query(None),
    decision: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    stmt = (
        select(AITradeDecision)
        .where(AITradeDecision.user_id == uuid.UUID(user_id))
        .order_by(desc(AITradeDecision.created_at))
    )
    if ticker:
        stmt = stmt.where(AITradeDecision.ticker == ticker.upper())
    if decision:
        stmt = stmt.where(AITradeDecision.decision == decision)
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    rows = result.scalars().all()

    count_stmt = select(func.count(AITradeDecision.id)).where(
        AITradeDecision.user_id == uuid.UUID(user_id)
    )
    if ticker:
        count_stmt = count_stmt.where(AITradeDecision.ticker == ticker.upper())
    if decision:
        count_stmt = count_stmt.where(AITradeDecision.decision == decision)
    total = (await session.execute(count_stmt)).scalar() or 0

    return {
        "total": total,
        "decisions": [
            {
                "id": str(d.id),
                "trigger_type": d.trigger_type,
                "ticker": d.ticker,
                "decision": d.decision,
                "decision_rationale": d.decision_rationale,
                "trade_params": d.trade_params,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in rows
        ],
    }
