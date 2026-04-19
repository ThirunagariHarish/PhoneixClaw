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
    auth_type: str = "bot"


class DiscoverChannelsRequest(BaseModel):
    token: str
    auth_type: str = "bot"
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
    deprecation_warning = None
    if payload.type == "discord" and payload.credentials:
        if payload.credentials.get("user_token") and not payload.credentials.get("bot_token"):
            deprecation_warning = (
                "DEPRECATED: user_token auth violates Discord TOS and will be removed. "
                "Please migrate to a Discord Bot token."
            )
            logger.warning("Connector creation with user_token for Discord: %s", payload.name)

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
    response = ConnectorResponse.from_model(connector)
    if deprecation_warning:
        from fastapi.responses import JSONResponse
        data = response.model_dump() if hasattr(response, "model_dump") else response.dict()
        data["deprecation_warning"] = deprecation_warning
        return JSONResponse(
            status_code=201, content=data,
            headers={"X-Deprecation-Warning": deprecation_warning},
        )
    return response


@router.get("/{connector_id}", response_model=ConnectorResponse)
async def get_connector(connector_id: str, session: DbSession):
    """Get a single connector by ID."""
    try:
        cid = uuid.UUID(connector_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Connector not found")
    result = await session.execute(
        select(Connector).where(Connector.id == cid)
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")
    return ConnectorResponse.from_model(connector)


@router.patch("/{connector_id}", response_model=ConnectorResponse)
async def update_connector(connector_id: str, payload: ConnectorUpdate, session: DbSession):
    """Update connector configuration or credentials."""
    try:
        cid = uuid.UUID(connector_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Connector not found")
    result = await session.execute(
        select(Connector).where(Connector.id == cid)
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


@router.post("/{connector_id}/migrate-to-bot")
async def migrate_connector_to_bot(
    connector_id: str,
    session: DbSession,
    bot_token: str = Query(..., description="New Discord Bot token to replace user token"),
):
    """Migrate a Discord connector from deprecated user_token to an official Bot token.

    Steps for the caller:
    1. Create a bot at https://discord.com/developers/applications
    2. Enable Message Content Intent under Privileged Gateway Intents
    3. Invite the bot to the target server with Read Messages + Read Message History
    4. Call this endpoint with the bot token
    """
    try:
        cid = uuid.UUID(connector_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Connector not found")

    result = await session.execute(select(Connector).where(Connector.id == cid))
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=404, detail="Connector not found")
    if connector.type != "discord":
        raise HTTPException(status_code=400, detail="Only Discord connectors can be migrated")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            "https://discord.com/api/v10/users/@me",
            headers={"Authorization": f"Bot {bot_token}"},
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Bot token validation failed (HTTP {resp.status_code}). "
            "Ensure the token is correct and the bot has been created.",
        )
    bot_user = resp.json()

    from shared.crypto.credentials import encrypt_credentials
    connector.credentials_encrypted = encrypt_credentials({"bot_token": bot_token})
    config = dict(connector.config or {})
    config["auth_type"] = "bot"
    connector.config = config
    connector.updated_at = datetime.now(timezone.utc)
    await session.commit()

    logger.info(
        "Connector %s migrated to bot token (bot user: %s)",
        connector_id, bot_user.get("username"),
    )
    return {
        "status": "migrated",
        "bot_username": bot_user.get("username"),
        "connector_id": connector_id,
        "message": "Connector now uses official Discord Bot token. Restart discord-ingestion service to apply.",
    }


@router.delete("/{connector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(connector_id: str, session: DbSession):
    """Delete a connector and its agent mappings."""
    try:
        cid = uuid.UUID(connector_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Connector not found")
    result = await session.execute(
        select(Connector).where(Connector.id == cid)
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
            bot_token = creds.get("bot_token", "")
            user_token = creds.get("user_token", "")
            if bot_token:
                auth_header = f"Bot {bot_token}" if not bot_token.startswith("Bot ") else bot_token
            elif user_token:
                logger.warning(
                    "Connector %s uses deprecated user_token. Migrate to a Bot token.",
                    connector_id,
                )
                auth_header = user_token
            else:
                return {"connection_status": "ERROR", "detail": "No Discord token in stored credentials"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": auth_header},
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

        elif connector.type == "whatsapp":
            # P15: Meta WhatsApp Cloud API — validate by fetching phone-number metadata
            access_token = creds.get("access_token", "")
            phone_id = creds.get("phone_number_id", "")
            if not access_token or not phone_id:
                return {"connection_status": "ERROR",
                        "detail": "Missing access_token or phone_number_id"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://graph.facebook.com/v18.0/{phone_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code == 200:
                    conn_status = "connected"
                    detail = resp.json().get("display_phone_number", "WhatsApp connected")
                else:
                    detail = f"WhatsApp API returned {resp.status_code}"

        elif connector.type == "telegram":
            # P15: Telegram Bot API — validate via getMe
            bot_token = creds.get("bot_token", "")
            if not bot_token:
                return {"connection_status": "ERROR", "detail": "Missing bot_token"}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
                if resp.status_code == 200 and resp.json().get("ok"):
                    conn_status = "connected"
                    detail = "@" + resp.json().get("result", {}).get("username", "bot")
                else:
                    detail = f"Telegram API returned {resp.status_code}"

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


# ── Webhook relay ingestion ──────────────────────────────────────────────────

class WebhookIngestPayload(BaseModel):
    content: str
    author: str = "webhook"
    channel: str = "webhook"
    timestamp: str | None = None
    message_id: str | None = None


@router.post("/{connector_id}/webhook-ingest", status_code=status.HTTP_201_CREATED)
async def webhook_ingest(
    connector_id: str,
    payload: WebhookIngestPayload,
    request: Request,
    session: DbSession,
):
    """Ingest a message via webhook relay — TOS-compliant alternative to direct Discord API access.

    Accepts messages forwarded by an external relay (Zapier, Make, a simple bot, etc.)
    and feeds them into the same channel_messages + Redis stream pipeline.
    Authenticates via X-Webhook-Secret header matching the connector's stored secret,
    or via the standard JWT if the caller is the connector owner.
    """
    import json as _json

    import redis.asyncio as aioredis

    result = await session.execute(
        select(Connector).where(Connector.id == uuid.UUID(connector_id))
    )
    connector = result.scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")

    webhook_secret = (connector.config or {}).get("webhook_secret", "")
    header_secret = request.headers.get("x-webhook-secret", "")

    user_id_str = getattr(request.state, "user_id", None)
    owner_match = user_id_str and connector.user_id and str(connector.user_id) == user_id_str

    if not owner_match and (not webhook_secret or header_secret != webhook_secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook secret")

    from shared.db.models.channel_message import ChannelMessage

    posted_at = datetime.now(timezone.utc)
    if payload.timestamp:
        try:
            posted_at = datetime.fromisoformat(payload.timestamp).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    platform_msg_id = payload.message_id or str(uuid.uuid4())

    existing = await session.execute(
        select(ChannelMessage).where(ChannelMessage.platform_message_id == platform_msg_id).limit(1)
    )
    if existing.scalar_one_or_none():
        return {"status": "duplicate", "message_id": platform_msg_id}

    import re
    tickers = list(set(re.findall(r"\$([A-Z]{1,5})\b", payload.content)))

    msg = ChannelMessage(
        id=uuid.uuid4(),
        connector_id=connector.id,
        channel=payload.channel,
        author=payload.author,
        content=payload.content,
        message_type="webhook",
        tickers_mentioned=tickers,
        raw_data={"source": "webhook_relay", "author": payload.author},
        platform_message_id=platform_msg_id,
        posted_at=posted_at,
    )
    session.add(msg)
    await session.commit()

    try:
        redis_url = __import__("os").environ.get("REDIS_URL", "redis://localhost:6379")
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        stream_payload = {
            "connector_id": str(connector.id),
            "channel": payload.channel,
            "author": payload.author,
            "content": payload.content,
            "tickers": _json.dumps(tickers),
            "timestamp": posted_at.isoformat(),
            "message_id": platform_msg_id,
            "sentiment": "neutral",
        }
        await redis_client.xadd(f"stream:channel:{connector.id}", stream_payload, maxlen=5000)
        await redis_client.xadd(f"stream:messages:{connector.id}", stream_payload, maxlen=5000)
        await redis_client.aclose()
    except Exception as exc:
        logger.warning("Redis publish failed for webhook ingest: %s", exc)

    return {"status": "ingested", "message_id": platform_msg_id, "tickers": tickers}


# ── Agent linking ────────────────────────────────────────────────────────────

@router.post("/{connector_id}/agents", status_code=status.HTTP_201_CREATED)
async def link_agent(connector_id: str, payload: ConnectorAgentLink, request: Request, session: DbSession):
    """Link an agent to a connector (optionally with a specific channel).

    Ownership check: the requesting user must own both the connector and the agent.
    Unauthenticated requests are rejected with 401.
    Duplicate links are returned as-is (idempotent).
    """
    from shared.db.models.agent import Agent

    # R-001: require authenticated caller — never skip ownership checks
    user_id_str = getattr(request.state, "user_id", None)
    if not user_id_str:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    user_id = uuid.UUID(user_id_str)

    # Resolve and validate IDs
    try:
        cid = uuid.UUID(connector_id)
        aid = uuid.UUID(payload.agent_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid UUID")

    connector = (await session.execute(
        select(Connector).where(Connector.id == cid)
    )).scalar_one_or_none()
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connector not found")
    if connector.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your connector")

    # Resolve and validate the agent
    agent = (await session.execute(
        select(Agent).where(Agent.id == aid)
    )).scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.user_id and agent.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your agent")

    # R-002: idempotent — return existing row rather than inserting a duplicate
    existing = (await session.execute(
        select(ConnectorAgent).where(
            ConnectorAgent.connector_id == cid,
            ConnectorAgent.agent_id == aid,
        ).limit(1)
    )).scalar_one_or_none()
    if existing:
        return {"id": str(existing.id), "connector_id": connector_id, "agent_id": payload.agent_id}

    link = ConnectorAgent(
        id=uuid.uuid4(),
        connector_id=cid,
        agent_id=aid,
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
