import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config.base_config import config
from shared.crypto.credentials import encrypt_credentials
from shared.models.database import get_session
from shared.models.trade import (
    AccountSourceMapping,
    Channel,
    ChatMessage,
    DataSource,
    RawMessage,
    Trade,
    TradePipeline,
    TradingAccount,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

_kafka_producer = None


def set_kafka_producer(producer):
    global _kafka_producer
    _kafka_producer = producer


class ChatSendRequest(BaseModel):
    message: str


class ChatMessageResponse(BaseModel):
    id: int
    content: str
    role: str
    trade_id: str | None
    created_at: str


async def _ensure_chat_pipeline(
    user_id: str, session: AsyncSession
) -> TradePipeline | None:
    """Lazily create a Chat data source, channel, and pipeline for the user."""
    user_uuid = uuid.UUID(user_id)

    result = await session.execute(
        select(TradePipeline)
        .join(DataSource, TradePipeline.data_source_id == DataSource.id)
        .where(
            TradePipeline.user_id == user_uuid,
            DataSource.source_type == "chat",
        )
        .limit(1)
    )
    pipeline = result.scalar_one_or_none()
    if pipeline:
        return pipeline

    acc_result = await session.execute(
        select(TradingAccount)
        .where(TradingAccount.user_id == user_uuid, TradingAccount.enabled.is_(True))
        .limit(1)
    )
    ta = acc_result.scalar_one_or_none()
    if not ta:
        logger.warning("No trading account for user %s; skipping chat pipeline creation", user_id)
        return None

    ds = DataSource(
        user_id=user_uuid,
        source_type="chat",
        display_name="Chat Widget",
        auth_type="none",
        credentials_encrypted=encrypt_credentials({}),
        connection_status="CONNECTED",
    )
    session.add(ds)
    await session.flush()

    ch = Channel(
        data_source_id=ds.id,
        channel_identifier="chat-widget",
        display_name="Chat Widget",
    )
    session.add(ch)
    await session.flush()

    mapping = AccountSourceMapping(
        trading_account_id=ta.id,
        channel_id=ch.id,
    )
    session.add(mapping)

    pipeline = TradePipeline(
        user_id=user_uuid,
        name="Chat Trade",
        data_source_id=ds.id,
        channel_id=ch.id,
        trading_account_id=ta.id,
        enabled=True,
        status="CONNECTED",
        auto_approve=True,
        paper_mode=False,
    )
    session.add(pipeline)
    await session.flush()

    logger.info("Created default Chat Trade pipeline %s for user %s", pipeline.id, user_id)
    return pipeline


@router.post("/send")
async def send_chat_message(
    body: ChatSendRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id

    msg = ChatMessage(
        user_id=uuid.UUID(user_id),
        content=body.message,
        role="user",
    )
    session.add(msg)

    raw_msg = RawMessage(
        user_id=uuid.UUID(user_id),
        source_type="chat",
        channel_name="chat-widget",
        author="You",
        content=body.message,
        source_message_id=None,
        raw_metadata={"origin": "chat-widget"},
    )
    session.add(raw_msg)
    await session.commit()
    await session.refresh(msg)

    parsed_trade_ids: list[str] = []
    system_reply_text = f"Signal received: \"{body.message}\". "

    try:
        from services.trade_parser.src.parser import parse_trade_message

        result = parse_trade_message(body.message)
        actions = result.get("actions", [])

        if actions:
            pipeline = await _ensure_chat_pipeline(user_id, session)

            if pipeline:
                ta_id = pipeline.trading_account_id
                is_auto = pipeline.auto_approve
                channel_id = pipeline.channel_id
            else:
                acc_result = await session.execute(
                    select(TradingAccount)
                    .where(
                        TradingAccount.user_id == uuid.UUID(user_id),
                        TradingAccount.enabled.is_(True),
                    )
                    .limit(1)
                )
                ta = acc_result.scalar_one_or_none()
                ta_id = ta.id if ta else None
                is_auto = config.gateway.approval_mode == "auto"
                channel_id = None

            status = "IN_PROGRESS" if is_auto else "PENDING"
            approved_by = "auto-chat" if is_auto else None
            approved_at = datetime.now(timezone.utc) if is_auto else None

            for action in actions:
                trade_id = uuid.uuid4()
                exp_val = action.get("expiration")
                expiration_dt = None
                if exp_val:
                    try:
                        expiration_dt = datetime.strptime(
                            str(exp_val), "%Y-%m-%d"
                        )
                    except (ValueError, TypeError):
                        pass

                trade = Trade(
                    trade_id=trade_id,
                    user_id=uuid.UUID(user_id),
                    trading_account_id=ta_id,
                    channel_id=channel_id,
                    ticker=action.get("ticker", ""),
                    strike=action.get("strike", 0),
                    option_type=action.get("option_type", "CALL"),
                    expiration=expiration_dt,
                    action=action.get("action", "BUY"),
                    quantity=str(action.get("quantity", 1)),
                    price=action.get("price", 0),
                    source="chat",
                    source_message_id=str(msg.id),
                    source_author="You",
                    raw_message=body.message,
                    status=status,
                    approved_by=approved_by,
                    approved_at=approved_at,
                )
                session.add(trade)
                parsed_trade_ids.append(str(trade_id))

            if pipeline:
                pipeline.trades_count = (pipeline.trades_count or 0) + len(actions)
                pipeline.last_message_at = datetime.now(timezone.utc)

            await session.commit()

            if is_auto:
                system_reply_text += (
                    f"Parsed {len(actions)} trade(s). Auto-approved. "
                    "Execution will attempt when market is open."
                )
            else:
                system_reply_text += (
                    f"Parsed {len(actions)} trade(s). Pending your approval "
                    "in the Trade Gateway."
                )

            if _kafka_producer and _kafka_producer.is_started and is_auto:
                for i, trade_id_str in enumerate(parsed_trade_ids):
                    act = actions[i] if i < len(actions) else {}
                    try:
                        await _kafka_producer.send(
                            topic="approved-trades",
                            value={
                                "trade_id": trade_id_str,
                                "user_id": user_id,
                                "trading_account_id": str(ta_id) if ta_id else None,
                                "channel_id": str(channel_id) if channel_id else "chat-widget",
                                "ticker": act.get("ticker", ""),
                                "strike": act.get("strike", 0),
                                "option_type": act.get("option_type", "CALL"),
                                "expiration": act.get("expiration"),
                                "action": act.get("action", "BUY"),
                                "quantity": act.get("quantity", 1),
                                "price": act.get("price", 0),
                                "source": "chat",
                                "raw_message": body.message,
                            },
                            key=trade_id_str,
                            headers=[("user_id", user_id.encode())],
                        )
                    except Exception:
                        logger.exception(
                            "Failed to publish trade %s to Kafka", trade_id_str
                        )
        else:
            system_reply_text += "No trade signal detected. Try format: BTO AAPL 190C 3/21 @ 2.50"
    except Exception:
        logger.exception("Chat sync parse failed for: %s", body.message[:80])
        system_reply_text += "Parse error — check format (e.g. BTO AAPL 190C 3/21 @ 2.50)"

    if not parsed_trade_ids and (_kafka_producer and _kafka_producer.is_started):
        try:
            await _kafka_producer.send(
                topic="raw-messages",
                value={
                    "content": body.message,
                    "user_id": user_id,
                    "author": user_id,
                    "source": "chat",
                    "source_type": "chat",
                    "channel_id": "chat-widget",
                    "channel_name": "chat-widget",
                    "message_id": str(msg.id),
                    "source_message_id": str(msg.id),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                key=user_id,
                headers=[
                    ("user_id", user_id.encode()),
                    ("source", b"chat"),
                ],
            )
        except Exception:
            logger.exception("Failed to publish chat message to Kafka")

    system_reply = ChatMessage(
        user_id=uuid.UUID(user_id),
        content=system_reply_text,
        role="system",
    )
    session.add(system_reply)
    await session.commit()
    await session.refresh(system_reply)

    return {
        "status": "sent",
        "message_id": msg.id,
        "system_reply": {
            "id": system_reply.id,
            "content": system_reply.content,
            "role": system_reply.role,
            "created_at": system_reply.created_at.isoformat() if system_reply.created_at else None,
        },
    }


@router.get("/history")
async def get_chat_history(
    request: Request,
    limit: int = Query(50, le=200),
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.user_id == uuid.UUID(user_id))
        .order_by(desc(ChatMessage.created_at))
        .limit(limit)
    )
    result = await session.execute(stmt)
    messages = list(reversed(result.scalars().all()))

    return [
        {
            "id": m.id,
            "content": m.content,
            "role": m.role,
            "trade_id": str(m.trade_id) if m.trade_id else None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]
