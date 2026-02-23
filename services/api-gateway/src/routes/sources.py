import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.crypto.credentials import decrypt_credentials, encrypt_credentials
from shared.models.database import get_session
from shared.models.trade import Channel, DataSource, RawMessage

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])

class SourceCreate(BaseModel):
    source_type: str
    display_name: str
    auth_type: str = "user_token"
    credentials: dict

class SourceResponse(BaseModel):
    id: str
    source_type: str
    display_name: str
    auth_type: str
    enabled: bool
    connection_status: str
    created_at: str

class ChannelCreate(BaseModel):
    channel_identifier: str
    display_name: str

class ChannelResponse(BaseModel):
    id: str
    channel_identifier: str
    display_name: str
    enabled: bool

@router.get("", response_model=list[SourceResponse])
async def list_sources(request: Request, session: AsyncSession = Depends(get_session)):
    user_id = request.state.user_id
    result = await session.execute(select(DataSource).where(DataSource.user_id == uuid.UUID(user_id)))
    return [_source_response(s) for s in result.scalars().all()]

async def _ensure_channels_from_credentials(source: DataSource, credentials: dict, session: AsyncSession) -> None:
    """Create Channel records from channel_ids in credentials. Skips duplicates."""
    channel_ids_raw = credentials.get("channel_ids", "")
    if not channel_ids_raw:
        return
    result = await session.execute(
        select(Channel.channel_identifier).where(Channel.data_source_id == source.id)
    )
    existing = {row[0] for row in result.fetchall()}
    for cid in channel_ids_raw.split(","):
        cid = cid.strip()
        if not cid or cid in existing:
            continue
        ch = Channel(
            data_source_id=source.id,
            channel_identifier=cid,
            display_name=f"Channel {cid}",
        )
        session.add(ch)
        existing.add(cid)


@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(req: SourceCreate, request: Request, session: AsyncSession = Depends(get_session)):
    user_id = request.state.user_id
    source = DataSource(
        user_id=uuid.UUID(user_id), source_type=req.source_type,
        display_name=req.display_name, auth_type=req.auth_type,
        credentials_encrypted=encrypt_credentials(req.credentials),
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    await _ensure_channels_from_credentials(source, req.credentials, session)
    await session.commit()
    return _source_response(source)

@router.delete("/{source_id}", status_code=204)
async def delete_source(source_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    user_id = request.state.user_id
    result = await session.execute(
        select(DataSource).where(
            DataSource.id == uuid.UUID(source_id),
            DataSource.user_id == uuid.UUID(user_id),
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    await session.delete(source)
    await session.commit()

@router.get("/{source_id}/channels", response_model=list[ChannelResponse])
async def list_channels(source_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Channel).where(Channel.data_source_id == uuid.UUID(source_id)))
    return [
        ChannelResponse(
            id=str(c.id), channel_identifier=c.channel_identifier,
            display_name=c.display_name, enabled=c.enabled,
        )
        for c in result.scalars().all()
    ]


@router.post("/{source_id}/sync-channels", response_model=list[ChannelResponse])
async def sync_channels(source_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    """Create Channel records from channel_ids in credentials for existing sources."""
    user_id = request.state.user_id
    result = await session.execute(
        select(DataSource).where(
            DataSource.id == uuid.UUID(source_id),
            DataSource.user_id == uuid.UUID(user_id),
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    creds = decrypt_credentials(source.credentials_encrypted)
    await _ensure_channels_from_credentials(source, creds, session)
    await session.commit()
    result = await session.execute(select(Channel).where(Channel.data_source_id == source.id))
    return [
        ChannelResponse(
            id=str(c.id), channel_identifier=c.channel_identifier,
            display_name=c.display_name, enabled=c.enabled,
        )
        for c in result.scalars().all()
    ]


@router.post("/{source_id}/channels", response_model=ChannelResponse, status_code=201)
async def add_channel(
    source_id: str, req: ChannelCreate, request: Request,
    session: AsyncSession = Depends(get_session),
):
    ch = Channel(
        data_source_id=uuid.UUID(source_id),
        channel_identifier=req.channel_identifier,
        display_name=req.display_name,
    )
    session.add(ch)
    await session.commit()
    await session.refresh(ch)
    return ChannelResponse(
        id=str(ch.id), channel_identifier=ch.channel_identifier,
        display_name=ch.display_name, enabled=ch.enabled,
    )

@router.post("/{source_id}/test")
async def test_connection(
    source_id: str, request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(DataSource).where(
            DataSource.id == uuid.UUID(source_id),
            DataSource.user_id == uuid.UUID(user_id),
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    creds = decrypt_credentials(source.credentials_encrypted)
    status = "ERROR"
    detail = ""

    if source.source_type == "discord":
        token = creds.get("user_token") or creds.get("bot_token", "")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": token},
                )
                if resp.status_code == 200:
                    status = "CONNECTED"
                    detail = resp.json().get("username", "")
                else:
                    detail = f"Discord API returned {resp.status_code}"
        except httpx.TimeoutException:
            detail = "Connection timed out"
        except Exception as exc:
            detail = str(exc)[:200]
    else:
        detail = f"Test not implemented for {source.source_type}"

    source.connection_status = status
    if status == "CONNECTED":
        source.last_connected_at = datetime.now(timezone.utc)
    source.updated_at = datetime.now(timezone.utc)
    await session.commit()

    return {
        "connection_status": status,
        "detail": detail,
    }


@router.post("/{source_id}/toggle")
async def toggle_source(
    source_id: str, request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(DataSource).where(
            DataSource.id == uuid.UUID(source_id),
            DataSource.user_id == uuid.UUID(user_id),
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    source.enabled = not source.enabled
    source.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(source)
    return _source_response(source)


@router.get("/{source_id}/messages")
async def list_source_messages(
    source_id: str, request: Request,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    stmt = (
        select(RawMessage)
        .where(
            RawMessage.user_id == uuid.UUID(user_id),
            RawMessage.data_source_id == uuid.UUID(source_id),
        )
        .order_by(desc(RawMessage.created_at))
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()

    count_stmt = select(func.count(RawMessage.id)).where(
        RawMessage.user_id == uuid.UUID(user_id),
        RawMessage.data_source_id == uuid.UUID(source_id),
    )
    total = (await session.execute(count_stmt)).scalar() or 0

    return {
        "total": total,
        "messages": [_raw_msg(m) for m in rows],
    }


def _raw_msg(m: RawMessage) -> dict:
    return {
        "id": str(m.id),
        "source_type": m.source_type,
        "channel_name": m.channel_name,
        "author": m.author,
        "content": m.content,
        "source_message_id": m.source_message_id,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _source_response(s: DataSource) -> SourceResponse:
    return SourceResponse(
        id=str(s.id), source_type=s.source_type,
        display_name=s.display_name, auth_type=s.auth_type,
        enabled=s.enabled, connection_status=s.connection_status,
        created_at=s.created_at.isoformat(),
    )
