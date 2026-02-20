import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.database import get_session
from shared.models.trade import AccountSourceMapping

router = APIRouter(prefix="/api/v1/mappings", tags=["mappings"])

class MappingCreate(BaseModel):
    trading_account_id: str
    channel_id: str
    config_overrides: dict | None = None

class MappingResponse(BaseModel):
    id: str
    trading_account_id: str
    channel_id: str
    config_overrides: dict
    enabled: bool

@router.get("", response_model=list[MappingResponse])
async def list_mappings(request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(AccountSourceMapping))
    return [_mapping_response(m) for m in result.scalars().all()]

@router.post("", response_model=MappingResponse, status_code=201)
async def create_mapping(req: MappingCreate, request: Request, session: AsyncSession = Depends(get_session)):
    mapping = AccountSourceMapping(
        trading_account_id=uuid.UUID(req.trading_account_id),
        channel_id=uuid.UUID(req.channel_id),
        config_overrides=req.config_overrides or {},
    )
    session.add(mapping)
    await session.commit()
    await session.refresh(mapping)
    return _mapping_response(mapping)

@router.delete("/{mapping_id}", status_code=204)
async def delete_mapping(mapping_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(AccountSourceMapping).where(AccountSourceMapping.id == uuid.UUID(mapping_id)))
    mapping = result.scalar_one_or_none()
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    await session.delete(mapping)
    await session.commit()

def _mapping_response(m: AccountSourceMapping) -> MappingResponse:
    return MappingResponse(
        id=str(m.id), trading_account_id=str(m.trading_account_id),
        channel_id=str(m.channel_id),
        config_overrides=m.config_overrides or {}, enabled=m.enabled,
    )
