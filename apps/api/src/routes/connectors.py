"""
Connector CRUD API routes.

M1.9: Connector management, credential encryption, test connection.
Discord discovery endpoints ported from v1 sources.py.
Reference: PRD Section 3.6, ArchitecturePlan §3.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from apps.api.src.deps import DbSession
from shared.db.models.connector import Connector, ConnectorAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/connectors", tags=["connectors"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class ConnectorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., max_length=30)
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, str] = Field(default_factory=dict)


class ConnectorUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, str] | None = None
    is_active: bool | None = None


class ConnectorAgentLink(BaseModel):
    agent_id: str
    channel: str = "*"


class ConnectorResponse(BaseModel):
    id: str
    name: str
    type: str
    status: str
    config: dict[str, Any]
    is_active: bool
    last_connected_at: str | None
    error_message: str | None
    created_at: str

    @classmethod
    def from_model(cls, c: Connector) -> "ConnectorResponse":
        return cls(
            id=str(c.id),
            name=c.name,
            type=c.type,
            status=c.status,
            config=c.config or {},
            is_active=c.is_active,
            last_connected_at=c.last_connected_at.isoformat() if c.last_connected_at else None,
            error_message=c.error_message,
            created_at=c.created_at.isoformat() if c.created_at else "",
        )


class DiscoverServersRequest(BaseModel):
    token: str
    auth_type: str = "user_token"


class DiscoverChannelsRequest(BaseModel):
    token: str
    auth_type: str = "user_token"
    server_id: str | None = None


# ── Discovery endpoints ──────────────────────────────────────────────────────

@router.post("/discover-servers")
async def discover_servers_endpoint(req: DiscoverServersRequest):
    """Discover Discord servers accessible with the given token."""
    from shared.discord_utils.channel_discovery import discover_servers
    try:
        servers = await discover_servers(req.token, auth_type=req.auth_type)
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="discord.py is not installed on the server",
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except Exception as exc:
        logger.exception("Server discovery failed")
        raise HTTPException(status_code=502, detail=f"Discovery failed: {str(exc)[:200]}")
    return {"servers": servers}


@router.post("/discover-channels")
async def discover_channels_endpoint(req: DiscoverChannelsRequest):
    """Discover Discord channels accessible with the given token, optionally filtered by server."""
    from shared.discord_utils.channel_discovery import discover_channels
    try:
        channels = await discover_channels(req.token, auth_type=req.auth_type)
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="discord.py is not installed on the server",
        )
    except TimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    except Exception as exc:
        logger.exception("Channel discovery failed")
        raise HTTPException(status_code=502, detail=f"Discovery failed: {str(exc)[:200]}")
    if req.server_id:
        channels = [c for c in channels if c.get("guild_id") == req.server_id]
    return {"channels": channels}


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ConnectorResponse])
async def list_connectors(session: DbSession):
    """List all configured connectors."""
    result = await session.execute(
        select(Connector).order_by(Connector.created_at.desc())
    )
    return [ConnectorResponse.from_model(c) for c in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ConnectorResponse)
async def create_connector(payload: ConnectorCreate, request: Request, session: DbSession):
    """Create a new connector with encrypted credentials."""
    encrypted_creds = None
    if payload.credentials:
        from shared.crypto.credentials import encrypt_credentials
        encrypted_creds = encrypt_credentials(payload.credentials)

    user_id_str = getattr(request.state, "user_id", None)
    user_id = uuid.UUID(user_id_str) if user_id_str else uuid.UUID("00000000-0000-0000-0000-000000000000")

    connector = Connector(
        id=uuid.uuid4(),
        name=payload.name,
        type=payload.type,
        config=payload.config,
        credentials_encrypted=encrypted_creds,
        user_id=user_id,
        status="disconnected",
    )
    session.add(connector)
    await session.commit()
    await session.refresh(connector)
    return ConnectorResponse.from_model(connector)


@router.get("/{connector_id}", response_model=ConnectorResponse)
async def get_connector(connector_id: str, session: DbSession):
    """Get a single connector by ID."""
    result = await session.execute(
        select(Connector).where(Connector.id == uuid.UUID(connector_id))
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")
    return ConnectorResponse.from_model(connector)


@router.patch("/{connector_id}", response_model=ConnectorResponse)
async def update_connector(connector_id: str, payload: ConnectorUpdate, session: DbSession):
    """Update connector configuration or credentials."""
    result = await session.execute(
        select(Connector).where(Connector.id == uuid.UUID(connector_id))
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    if payload.name is not None:
        connector.name = payload.name
    if payload.config is not None:
        connector.config = payload.config
    if payload.is_active is not None:
        connector.is_active = payload.is_active
    if payload.credentials is not None:
        from shared.crypto.credentials import encrypt_credentials
        connector.credentials_encrypted = encrypt_credentials(payload.credentials)

    connector.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(connector)
    return ConnectorResponse.from_model(connector)


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(connector_id: str, session: DbSession):
    """Delete a connector and its agent mappings."""
    result = await session.execute(
        select(Connector).where(Connector.id == uuid.UUID(connector_id))
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")
    await session.delete(connector)
    await session.commit()


# ── Test connection ──────────────────────────────────────────────────────────

@router.post("/{connector_id}/test")
async def test_connector(connector_id: str, session: DbSession):
    """Test connectivity for a connector by validating credentials against the upstream API."""
    result = await session.execute(
        select(Connector).where(Connector.id == uuid.UUID(connector_id))
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    conn_status = "ERROR"
    detail = ""

    try:
        from shared.crypto.credentials import decrypt_credentials
        creds = decrypt_credentials(connector.credentials_encrypted) if connector.credentials_encrypted else {}
    except Exception:
        logger.exception("Failed to decrypt credentials for connector %s", connector_id)
        return {"connection_status": "ERROR", "detail": "Could not decrypt stored credentials"}

    try:
        if connector.type == "discord":
            token = creds.get("user_token") or creds.get("bot_token", "")
            if not token:
                return {"connection_status": "ERROR", "detail": "No Discord token in stored credentials"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": token},
                )
                if resp.status_code == 200:
                    conn_status = "connected"
                    detail = resp.json().get("username", "")
                else:
                    detail = f"Discord API returned {resp.status_code}"
        else:
            conn_status = "connected"
            detail = f"Test not fully implemented for {connector.type}"
    except httpx.TimeoutException:
        detail = "Connection timed out"
    except Exception as exc:
        detail = str(exc)[:200]

    connector.status = conn_status
    if conn_status == "connected":
        connector.last_connected_at = datetime.now(timezone.utc)
    connector.error_message = detail if conn_status == "ERROR" else None
    connector.updated_at = datetime.now(timezone.utc)
    await session.commit()

    return {"connection_status": conn_status, "detail": detail}


# ── Agent linking ────────────────────────────────────────────────────────────

@router.post("/{connector_id}/agents", status_code=status.HTTP_201_CREATED)
async def link_agent(connector_id: str, payload: ConnectorAgentLink, session: DbSession):
    """Link an agent to a connector (optionally with a specific channel)."""
    link = ConnectorAgent(
        id=uuid.uuid4(),
        connector_id=uuid.UUID(connector_id),
        agent_id=uuid.UUID(payload.agent_id),
        channel=payload.channel,
    )
    session.add(link)
    await session.commit()
    return {"id": str(link.id), "connector_id": connector_id, "agent_id": payload.agent_id}


@router.get("/{connector_id}/agents")
async def list_connector_agents(connector_id: str, session: DbSession):
    """List all agents linked to a connector."""
    result = await session.execute(
        select(ConnectorAgent).where(ConnectorAgent.connector_id == uuid.UUID(connector_id))
    )
    links = result.scalars().all()
    return [
        {
            "id": str(l.id),
            "agent_id": str(l.agent_id),
            "channel": l.channel,
            "is_active": l.is_active,
        }
        for l in links
    ]
