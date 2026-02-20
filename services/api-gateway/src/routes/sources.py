import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.crypto.credentials import encrypt_credentials
from shared.models.database import get_session
from shared.models.trade import Channel, DataSource

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

def _source_response(s: DataSource) -> SourceResponse:
    return SourceResponse(
        id=str(s.id), source_type=s.source_type,
        display_name=s.display_name, auth_type=s.auth_type,
        enabled=s.enabled, connection_status=s.connection_status,
        created_at=s.created_at.isoformat(),
    )
