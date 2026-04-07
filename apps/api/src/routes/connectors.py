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
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

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
    tags: list[str] = Field(default_factory=list)


class ConnectorUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, str] | None = None
    is_active: bool | None = None
    tags: list[str] | None = None


class ConnectorAgentLink(BaseModel):
    agent_id: str
    channel: str = "*"


class ConnectorResponse(BaseModel):
    id: str
    name: str
    type: str
    status: str
    config: dict[str, Any]
    tags: list[str]
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
            tags=c.tags if c.tags else [],
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
async def list_connectors(
    session: DbSession,
    tags: str | None = Query(None, description="Comma-separated tags to filter by"),
    connector_type: str | None = Query(None, alias="type"),
):
    """List all configured connectors, optionally filtered by tags or type."""
    query = select(Connector).order_by(Connector.created_at.desc())
    if connector_type:
        query = query.where(Connector.type == connector_type)
    result = await session.execute(query)
    connectors = result.scalars().all()

    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        connectors = [
            c for c in connectors
            if c.tags and any(t.lower() in [ct.lower() for ct in (c.tags or [])] for t in tag_list)
        ]

    return [ConnectorResponse.from_model(c) for c in connectors]


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
        tags=payload.tags or [],
        user_id=user_id,
        status="disconnected",
    )
    try:
        session.add(connector)
        await session.commit()
        await session.refresh(connector)
    except IntegrityError as exc:
        await session.rollback()
        orig = str(getattr(exc, "orig", exc))[:400]
        logger.error("Connector IntegrityError: %s", orig)
        # Detect the common cause — missing `tags` column from migration 014
        if "tags" in orig.lower() or "column" in orig.lower():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Database schema out of date. A required column is missing. "
                    "Run `alembic -c shared/db/migrations/alembic.ini upgrade head` "
                    f"inside the API container. Details: {orig}"
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Database constraint violation: {orig}",
        )
    return ConnectorResponse.from_model(connector)


@router.post("/{connector_id}/test")
async def test_connector(connector_id: str, session: DbSession):
    """Test a connector's credentials (currently supports robinhood).

    Returns {success: bool, ...details} so the dashboard can verify credentials
    at connector-creation time rather than at agent-spawn time.
    """
    result = await session.execute(
        select(Connector).where(Connector.id == uuid.UUID(connector_id))
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    if connector.type != "robinhood":
        return {
            "success": False,
            "error": f"Test not yet implemented for connector type '{connector.type}'",
        }

    try:
        from shared.crypto.credentials import decrypt_credentials
        creds = decrypt_credentials(connector.credentials_encrypted) if connector.credentials_encrypted else {}
    except Exception as exc:
        return {"success": False, "error": f"Failed to decrypt credentials: {exc}"}

    username = creds.get("username", "")
    password = creds.get("password", "")
    totp_secret = creds.get("totp_secret", "")

    if not username or not password:
        return {"success": False, "error": "Missing username or password in credentials"}

    # Attempt login via robin_stocks (best-effort; may require TOTP)
    try:
        import robin_stocks.robinhood as rh  # type: ignore
        import pyotp  # type: ignore
        totp_code = pyotp.TOTP(totp_secret).now() if totp_secret else None
        rh.login(username, password, mfa_code=totp_code, store_session=False)
        try:
            account = rh.profiles.load_account_profile()
            buying_power = float(account.get("buying_power", 0))
        except Exception:
            buying_power = None
        try:
            rh.logout()
        except Exception:
            pass
        return {
            "success": True,
            "username": username,
            "has_totp": bool(totp_secret),
            "buying_power": buying_power,
        }
    except ImportError as exc:
        return {
            "success": False,
            "error": f"robin_stocks or pyotp not installed in this environment: {exc}",
        }
    except Exception as exc:
        return {"success": False, "error": f"Login failed: {str(exc)[:300]}"}


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
    if payload.tags is not None:
        connector.tags = payload.tags
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

    config = connector.config or {}

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

        elif connector.type == "reddit":
            client_id = creds.get("client_id", "")
            client_secret = creds.get("client_secret", "")
            user_agent = creds.get("user_agent", "PhoenixTrade/1.0")
            if not client_id or not client_secret:
                return {"connection_status": "ERROR", "detail": "Missing Reddit client_id or client_secret"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://www.reddit.com/api/v1/access_token",
                    data={"grant_type": "client_credentials"},
                    auth=(client_id, client_secret),
                    headers={"User-Agent": user_agent},
                )
                if resp.status_code == 200 and "access_token" in resp.json():
                    conn_status = "connected"
                    detail = "Reddit OAuth credentials valid"
                else:
                    detail = f"Reddit OAuth returned {resp.status_code}: {resp.text[:100]}"

        elif connector.type == "twitter":
            bearer = creds.get("bearer_token", "")
            if not bearer:
                return {"connection_status": "ERROR", "detail": "Missing Twitter bearer_token"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.twitter.com/2/users/me",
                    headers={"Authorization": f"Bearer {bearer}"},
                )
                if resp.status_code == 200:
                    conn_status = "connected"
                    detail = resp.json().get("data", {}).get("username", "Authenticated")
                elif resp.status_code == 403:
                    conn_status = "connected"
                    detail = "Bearer token valid (app-only auth)"
                else:
                    detail = f"Twitter API returned {resp.status_code}"

        elif connector.type == "unusual_whales":
            api_key = creds.get("api_key", "")
            if not api_key:
                return {"connection_status": "ERROR", "detail": "Missing Unusual Whales API key"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.unusualwhales.com/api/stock/SPY/options-volume",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code == 200:
                    conn_status = "connected"
                    detail = "Unusual Whales API key valid"
                elif resp.status_code == 401:
                    detail = "Invalid API key"
                else:
                    detail = f"Unusual Whales API returned {resp.status_code}"

        elif connector.type == "news_api":
            api_key = creds.get("api_key", "")
            if not api_key:
                return {"connection_status": "ERROR", "detail": "Missing News API key"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://newsapi.org/v2/top-headlines?country=us&pageSize=1&apiKey={api_key}",
                )
                if resp.status_code == 200:
                    conn_status = "connected"
                    detail = "News API key valid"
                elif resp.status_code == 401:
                    detail = "Invalid API key"
                else:
                    detail = f"News API returned {resp.status_code}"

        elif connector.type == "alpaca":
            api_key = creds.get("api_key", "")
            api_secret = creds.get("api_secret", "")
            if not api_key or not api_secret:
                return {"connection_status": "ERROR", "detail": "Missing Alpaca API key or secret"}
            mode = config.get("mode", "paper")
            base = "https://api.alpaca.markets" if mode == "live" else "https://paper-api.alpaca.markets"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{base}/v2/account",
                    headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret},
                )
                if resp.status_code == 200:
                    conn_status = "connected"
                    acct = resp.json()
                    detail = f"Account {acct.get('account_number', '')} ({mode})"
                elif resp.status_code == 403:
                    detail = "Invalid API credentials"
                else:
                    detail = f"Alpaca API returned {resp.status_code}"

        elif connector.type == "tradier":
            api_key = creds.get("api_key", "")
            if not api_key:
                return {"connection_status": "ERROR", "detail": "Missing Tradier API key"}
            sandbox = config.get("sandbox", True)
            base = "https://sandbox.tradier.com" if sandbox else "https://api.tradier.com"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{base}/v1/user/profile",
                    headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                )
                if resp.status_code == 200:
                    conn_status = "connected"
                    detail = "Tradier credentials valid"
                elif resp.status_code == 401:
                    detail = "Invalid API key"
                else:
                    detail = f"Tradier API returned {resp.status_code}"

        elif connector.type == "ibkr":
            conn_status = "connected"
            host = config.get("host", "127.0.0.1")
            port = config.get("port", 7497)
            detail = f"IBKR configured for {host}:{port} (connect via TWS/Gateway)"

        elif connector.type == "robinhood":
            username = creds.get("username", "")
            password = creds.get("password", "")
            if not username or not password:
                return {"connection_status": "ERROR", "detail": "Missing Robinhood username or password"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.robinhood.com/",
                    headers={"User-Agent": "PhoenixTrade/1.0"},
                )
                if resp.status_code == 200:
                    conn_status = "connected"
                    detail = f"Robinhood credentials stored for {username}"
                else:
                    detail = f"Robinhood API returned {resp.status_code}"

        elif connector.type == "custom_webhook":
            conn_status = "connected"
            detail = "Webhook endpoint is ready to receive signals"

        elif connector.type == "yfinance":
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://query1.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=1d",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if resp.status_code == 200:
                    conn_status = "connected"
                    detail = "Yahoo Finance data accessible (no API key required)"
                else:
                    detail = f"Yahoo Finance returned {resp.status_code}"

        elif connector.type == "polygon":
            api_key = creds.get("api_key", "")
            if not api_key:
                return {"connection_status": "ERROR", "detail": "Missing Polygon API key"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.polygon.io/v2/aggs/ticker/SPY/range/1/day/2024-01-02/2024-01-02?apiKey={api_key}",
                )
                if resp.status_code == 200:
                    conn_status = "connected"
                    detail = "Polygon API key valid"
                elif resp.status_code == 403:
                    detail = "Invalid or expired API key"
                else:
                    detail = f"Polygon API returned {resp.status_code}"

        elif connector.type == "alphavantage":
            api_key = creds.get("api_key", "")
            if not api_key:
                return {"connection_status": "ERROR", "detail": "Missing Alpha Vantage API key"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=SPY&apikey={api_key}",
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if "Global Quote" in data:
                        conn_status = "connected"
                        detail = "Alpha Vantage API key valid"
                    elif "Note" in data or "Information" in data:
                        detail = "Rate limit hit or invalid key"
                    else:
                        detail = "Unexpected Alpha Vantage response"
                else:
                    detail = f"Alpha Vantage returned {resp.status_code}"

        else:
            conn_status = "connected"
            detail = f"No specific test for {connector.type}"

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


# ── History pull ─────────────────────────────────────────────────────────────

@router.post("/{connector_id}/pull-history")
async def pull_connector_history(connector_id: str, session: DbSession):
    """Trigger historical message pull for a connector. Stores messages in channel_messages table."""
    result = await session.execute(
        select(Connector).where(Connector.id == uuid.UUID(connector_id))
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    try:
        from shared.crypto.credentials import decrypt_credentials
        creds = decrypt_credentials(connector.credentials_encrypted) if connector.credentials_encrypted else {}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not decrypt credentials")

    from services.message_ingestion.src.orchestrator import ingest_history
    try:
        summary = await ingest_history(
            session=session,
            connector_id=connector.id,
            connector_type=connector.type,
            credentials=creds,
            config=connector.config or {},
        )
    except Exception as exc:
        logger.exception("History pull failed for connector %s", connector_id)
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(exc)[:200]}")

    return {"status": "complete", **summary}


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
