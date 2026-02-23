import logging
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.crypto.credentials import decrypt_credentials, encrypt_credentials
from shared.models.database import get_session
from shared.models.trade import Channel, DataSource, RawMessage, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])

class SourceCreate(BaseModel):
    source_type: str
    display_name: str
    auth_type: str = "user_token"
    credentials: dict
    server_id: str | None = None
    server_name: str | None = None

class SourceResponse(BaseModel):
    id: str
    source_type: str
    display_name: str
    auth_type: str
    enabled: bool
    connection_status: str
    server_id: str | None = None
    server_name: str | None = None
    created_at: str
    owner_email: str | None = None
    owner_name: str | None = None

class DiscoverServersRequest(BaseModel):
    token: str
    auth_type: str = "user_token"

class ChannelCreate(BaseModel):
    channel_identifier: str
    display_name: str

class ChannelResponse(BaseModel):
    id: str
    channel_identifier: str
    display_name: str
    guild_id: str | None = None
    guild_name: str | None = None
    enabled: bool

@router.get("", response_model=list[SourceResponse])
async def list_sources(request: Request, session: AsyncSession = Depends(get_session)):
    user_id = request.state.user_id
    is_admin = getattr(request.state, "is_admin", False)
    if is_admin:
        stmt = (
            select(DataSource, User.email, User.name)
            .join(User, DataSource.user_id == User.id)
            .order_by(DataSource.created_at)
        )
        result = await session.execute(stmt)
        return [
            _source_response(s, owner_email=email, owner_name=name)
            for s, email, name in result.all()
        ]
    result = await session.execute(select(DataSource).where(DataSource.user_id == uuid.UUID(user_id)))
    return [_source_response(s) for s in result.scalars().all()]

async def _ensure_channels_from_credentials(source: DataSource, credentials: dict, session: AsyncSession) -> int:
    """Create Channel records from channel_ids in credentials. Skips duplicates.

    Handles channel_ids as a comma-separated string or a list of strings/ints.
    Returns the number of new channels created.
    """
    channel_ids_raw = credentials.get("channel_ids", "")
    if not channel_ids_raw:
        return 0

    if isinstance(channel_ids_raw, list):
        ids = [str(c).strip() for c in channel_ids_raw]
    else:
        ids = [c.strip() for c in str(channel_ids_raw).split(",")]

    ids = [c for c in ids if c]
    if not ids:
        return 0

    result = await session.execute(
        select(Channel.channel_identifier).where(Channel.data_source_id == source.id)
    )
    existing = {row[0] for row in result.fetchall()}
    created = 0
    for cid in ids:
        if cid in existing:
            continue
        ch = Channel(
            data_source_id=source.id,
            channel_identifier=cid,
            display_name=f"Channel {cid}",
        )
        session.add(ch)
        existing.add(cid)
        created += 1
    logger.info("Ensured channels for source %s: %d new, %d total", source.id, created, len(existing))
    return created


@router.post("/discover-servers")
async def discover_servers_endpoint(req: DiscoverServersRequest, request: Request):
    """Discover Discord servers accessible with the given token."""
    from shared.discord_utils.channel_discovery import discover_servers
    try:
        servers = await discover_servers(req.token, auth_type=req.auth_type)
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except Exception as exc:
        logger.exception("Server discovery failed")
        raise HTTPException(status_code=502, detail=f"Discovery failed: {str(exc)[:200]}")
    return {"servers": servers}


@router.post("", response_model=SourceResponse, status_code=201)
async def create_source(req: SourceCreate, request: Request, session: AsyncSession = Depends(get_session)):
    user_id = request.state.user_id
    source = DataSource(
        user_id=uuid.UUID(user_id), source_type=req.source_type,
        display_name=req.display_name, auth_type=req.auth_type,
        credentials_encrypted=encrypt_credentials(req.credentials),
        server_id=req.server_id,
        server_name=req.server_name,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    await _ensure_channels_from_credentials(source, req.credentials, session)
    await session.commit()
    return _source_response(source)

@router.delete("/{source_id}", status_code=204)
async def delete_source(source_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    source = await _get_source_for_user_or_admin(source_id, request, session)
    await session.delete(source)
    await session.commit()

async def _get_source_for_user_or_admin(
    source_id: str, request: Request, session: AsyncSession,
) -> DataSource:
    """Fetch a DataSource by id. Admins can access any source; regular users only their own."""
    user_id = request.state.user_id
    is_admin = getattr(request.state, "is_admin", False)
    if is_admin:
        result = await session.execute(
            select(DataSource).where(DataSource.id == uuid.UUID(source_id))
        )
    else:
        result = await session.execute(
            select(DataSource).where(
                DataSource.id == uuid.UUID(source_id),
                DataSource.user_id == uuid.UUID(user_id),
            )
        )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


def _channel_responses(channels) -> list[ChannelResponse]:
    return [
        ChannelResponse(
            id=str(c.id), channel_identifier=c.channel_identifier,
            display_name=c.display_name,
            guild_id=getattr(c, "guild_id", None),
            guild_name=getattr(c, "guild_name", None),
            enabled=c.enabled,
        )
        for c in channels
    ]


@router.get("/{source_id}/channels", response_model=list[ChannelResponse])
async def list_channels(source_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    source = await _get_source_for_user_or_admin(source_id, request, session)
    result = await session.execute(select(Channel).where(Channel.data_source_id == source.id))
    channels = result.scalars().all()

    if not channels:
        try:
            creds = decrypt_credentials(source.credentials_encrypted)
            created = await _ensure_channels_from_credentials(source, creds, session)
            if created:
                await session.commit()
                result = await session.execute(select(Channel).where(Channel.data_source_id == source.id))
                channels = result.scalars().all()
        except Exception:
            logger.exception("Lazy channel sync failed for source %s", source_id)

    return _channel_responses(channels)


@router.post("/{source_id}/sync-channels", response_model=list[ChannelResponse])
async def sync_channels(source_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    """Discover channels from Discord server and sync them to DB."""
    source = await _get_source_for_user_or_admin(source_id, request, session)
    creds = decrypt_credentials(source.credentials_encrypted)

    if source.source_type == "discord":
        token = creds.get("user_token") or creds.get("bot_token", "")
        if not token:
            raise HTTPException(status_code=400, detail="No Discord token in credentials")
        try:
            from shared.discord_utils.channel_discovery import discover_channels
            discovered = await discover_channels(token, auth_type=source.auth_type)
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc))
        except Exception as exc:
            logger.exception("Channel discovery failed for source %s", source_id)
            raise HTTPException(status_code=502, detail=f"Discovery failed: {str(exc)[:200]}")

        if source.server_id:
            discovered = [
                ch for ch in discovered if ch.get("guild_id") == source.server_id
            ]

        result = await session.execute(
            select(Channel.channel_identifier).where(Channel.data_source_id == source.id)
        )
        existing = {row[0] for row in result.fetchall()}
        created = 0
        for ch_info in discovered:
            cid = ch_info["channel_id"]
            if cid in existing:
                continue
            guild_name = ch_info.get("guild_name", "")
            ch_name = ch_info.get("channel_name", cid)
            display = f"{guild_name} / #{ch_name}" if guild_name else f"#{ch_name}"
            ch = Channel(
                data_source_id=source.id,
                channel_identifier=cid,
                display_name=display[:100],
                guild_id=ch_info.get("guild_id"),
                guild_name=guild_name[:200] if guild_name else None,
            )
            session.add(ch)
            existing.add(cid)
            created += 1
        if created:
            await session.commit()
        logger.info("Discovered %d new channels for source %s", created, source_id)
    else:
        await _ensure_channels_from_credentials(source, creds, session)
        await session.commit()

    result = await session.execute(select(Channel).where(Channel.data_source_id == source.id))
    channels = result.scalars().all()
    if not channels:
        raise HTTPException(
            status_code=400,
            detail="No channels discovered. Check that the token has access to at least one server.",
        )
    return _channel_responses(channels)


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
    source = await _get_source_for_user_or_admin(source_id, request, session)

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
    source = await _get_source_for_user_or_admin(source_id, request, session)

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


def _source_response(
    s: DataSource,
    owner_email: str | None = None,
    owner_name: str | None = None,
) -> SourceResponse:
    return SourceResponse(
        id=str(s.id), source_type=s.source_type,
        display_name=s.display_name, auth_type=s.auth_type,
        enabled=s.enabled, connection_status=s.connection_status,
        server_id=getattr(s, "server_id", None),
        server_name=getattr(s, "server_name", None),
        created_at=s.created_at.isoformat(),
        owner_email=owner_email,
        owner_name=owner_name,
    )
