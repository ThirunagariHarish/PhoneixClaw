"""
Agent Knowledge Wiki API routes.

Endpoints:
  GET    /api/v2/agents/{agent_id}/wiki
  GET    /api/v2/agents/{agent_id}/wiki/export
  POST   /api/v2/agents/{agent_id}/wiki/query
  GET    /api/v2/agents/{agent_id}/wiki/{entry_id}
  GET    /api/v2/agents/{agent_id}/wiki/{entry_id}/versions
  POST   /api/v2/agents/{agent_id}/wiki
  PATCH  /api/v2/agents/{agent_id}/wiki/{entry_id}
  DELETE /api/v2/agents/{agent_id}/wiki/{entry_id}
  GET    /api/v2/brain/wiki   (brain_router)
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from apps.api.src.deps import DbSession
from apps.api.src.repositories.wiki_repo import WikiRepository
from shared.db.models.agent import Agent
from shared.db.models.wiki import VALID_WIKI_CATEGORIES, AgentWikiEntry

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/v2/agents", tags=["wiki"])
brain_router = APIRouter(prefix="/api/v2/brain", tags=["wiki-brain"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class WikiEntryCreate(BaseModel):
    category: str
    subcategory: str | None = None
    title: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1)
    tags: list[str] = []
    symbols: list[str] = []
    confidence_score: float = Field(0.5, ge=0.0, le=1.0)
    trade_ref_ids: list[str] = []
    is_shared: bool = False

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in VALID_WIKI_CATEGORIES:
            raise ValueError(
                f"Invalid category '{v}'. Must be one of: {sorted(VALID_WIKI_CATEGORIES)}"
            )
        return v


class WikiEntryUpdate(BaseModel):
    category: str | None = None
    subcategory: str | None = None
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    symbols: list[str] | None = None
    confidence_score: float | None = Field(None, ge=0.0, le=1.0)
    is_shared: bool | None = None
    change_reason: str | None = None

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_WIKI_CATEGORIES:
            raise ValueError(
                f"Invalid category '{v}'. Must be one of: {sorted(VALID_WIKI_CATEGORIES)}"
            )
        return v


class WikiEntryResponse(BaseModel):
    id: str
    agent_id: str
    category: str
    subcategory: str | None
    title: str
    content: str
    tags: list[str]
    symbols: list[str]
    confidence_score: float
    trade_ref_ids: list[str]
    created_by: str
    is_active: bool
    is_shared: bool
    version: int
    created_at: str
    updated_at: str


class WikiVersionResponse(BaseModel):
    id: str
    entry_id: str
    version: int
    content: str
    updated_by: str | None
    updated_at: str
    change_reason: str | None


class WikiQueryRequest(BaseModel):
    query_text: str = Field(..., min_length=1)
    category: str | None = None
    top_k: int = Field(10, ge=1, le=50)
    include_shared: bool = True


class WikiListResponse(BaseModel):
    entries: list[WikiEntryResponse]
    total: int
    page: int
    per_page: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialize_entry(entry: AgentWikiEntry) -> WikiEntryResponse:
    return WikiEntryResponse(
        id=str(entry.id),
        agent_id=str(entry.agent_id),
        category=entry.category,
        subcategory=entry.subcategory,
        title=entry.title,
        content=entry.content,
        tags=list(entry.tags or []),
        symbols=list(entry.symbols or []),
        confidence_score=entry.confidence_score,
        trade_ref_ids=[str(r) for r in (entry.trade_ref_ids or [])],
        created_by=entry.created_by,
        is_active=entry.is_active,
        is_shared=entry.is_shared,
        version=entry.version,
        created_at=entry.created_at.isoformat() if entry.created_at else "",
        updated_at=entry.updated_at.isoformat() if entry.updated_at else "",
    )


async def _get_agent_and_verify(agent_id: str, request: Request, session) -> Agent:
    """Fetch the agent and enforce IDOR ownership check."""
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent_id format")

    agent = await session.get(Agent, agent_uuid)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    requesting_user_id = getattr(request.state, "user_id", None)
    is_admin = getattr(request.state, "is_admin", False)

    if not is_admin and str(agent.user_id) != str(requesting_user_id):
        raise HTTPException(status_code=403, detail="Access denied")

    return agent


def _render_markdown_export(entries: list[AgentWikiEntry]) -> str:
    """Render wiki entries as a Markdown document grouped by category."""
    by_category: dict[str, list[AgentWikiEntry]] = defaultdict(list)
    for e in entries:
        by_category[e.category].append(e)

    lines = ["# Agent Wiki Export", ""]
    for category in sorted(by_category.keys()):
        lines.append(f"## Category: {category}")
        lines.append("")
        for entry in by_category[category]:
            lines.append(f"### {entry.title}")
            tags_str = ", ".join(entry.tags or []) or "—"
            symbols_str = ", ".join(entry.symbols or []) or "—"
            updated_str = entry.updated_at.strftime("%Y-%m-%d") if entry.updated_at else "—"
            lines.append(
                f"**Confidence:** {entry.confidence_score:.2f} | "
                f"**Tags:** {tags_str} | "
                f"**Symbols:** {symbols_str}"
            )
            lines.append(f"**Updated:** {updated_str}")
            lines.append("")
            lines.append(entry.content)
            lines.append("")
            lines.append("---")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent-scoped endpoints  (router: /api/v2/agents)
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/wiki", response_model=WikiListResponse)
async def list_wiki_entries(
    agent_id: str,
    request: Request,
    session: DbSession,
    category: str | None = Query(None),
    tag: str | None = Query(None),
    symbol: str | None = Query(None),
    search: str | None = Query(None),
    is_shared: bool | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
) -> WikiListResponse:
    agent = await _get_agent_and_verify(agent_id, request, session)
    repo = WikiRepository(session)
    user_id = getattr(request.state, "user_id", None)

    skip = (page - 1) * per_page
    entries, total = await repo.list_for_agent(
        agent_id=agent.id,
        user_id=user_id,
        category=category,
        tag=tag,
        symbol=symbol,
        search=search,
        is_shared=is_shared,
        skip=skip,
        limit=per_page,
    )
    return WikiListResponse(
        entries=[_serialize_entry(e) for e in entries],
        total=total,
        page=page,
        per_page=per_page,
    )


# NOTE: /export and /query must be registered BEFORE /{entry_id} to avoid path conflicts.


@router.get("/{agent_id}/wiki/export")
async def export_wiki(
    agent_id: str,
    request: Request,
    session: DbSession,
    format: str = Query("json", pattern="^(json|markdown)$"),
):
    agent = await _get_agent_and_verify(agent_id, request, session)
    repo = WikiRepository(session)
    entries = await repo.export_entries(agent.id, fmt=format)

    if format == "markdown":
        md_content = _render_markdown_export(entries)
        return Response(content=md_content, media_type="text/markdown")

    # JSON list
    return [_serialize_entry(e) for e in entries]


@router.post("/{agent_id}/wiki/query", response_model=list[WikiEntryResponse])
async def query_wiki(
    agent_id: str,
    request: Request,
    session: DbSession,
    body: WikiQueryRequest,
) -> list[WikiEntryResponse]:
    agent = await _get_agent_and_verify(agent_id, request, session)
    user_id = getattr(request.state, "user_id", None)
    repo = WikiRepository(session)

    entries = await repo.query_entries(
        agent_id=agent.id,
        query_text=body.query_text,
        category=body.category,
        top_k=body.top_k,
        include_shared=body.include_shared,
        requesting_user_id=user_id,
    )
    return [_serialize_entry(e) for e in entries]


@router.get("/{agent_id}/wiki/{entry_id}", response_model=WikiEntryResponse)
async def get_wiki_entry(
    agent_id: str,
    entry_id: str,
    request: Request,
    session: DbSession,
) -> WikiEntryResponse:
    agent = await _get_agent_and_verify(agent_id, request, session)
    repo = WikiRepository(session)

    try:
        entry_uuid = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id format")

    entry = await repo.get_entry(entry_uuid, agent.id)
    if not entry:
        raise HTTPException(status_code=404, detail="Wiki entry not found")
    return _serialize_entry(entry)


@router.get("/{agent_id}/wiki/{entry_id}/versions", response_model=list[WikiVersionResponse])
async def get_wiki_entry_versions(
    agent_id: str,
    entry_id: str,
    request: Request,
    session: DbSession,
) -> list[WikiVersionResponse]:
    agent = await _get_agent_and_verify(agent_id, request, session)
    repo = WikiRepository(session)

    try:
        entry_uuid = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id format")

    # Verify the entry belongs to the agent
    entry = await repo.get_entry(entry_uuid, agent.id)
    if not entry:
        raise HTTPException(status_code=404, detail="Wiki entry not found")

    versions = await repo.get_versions(entry_uuid)
    return [
        WikiVersionResponse(
            id=str(v.id),
            entry_id=str(v.entry_id),
            version=v.version,
            content=v.content,
            updated_by=v.updated_by,
            updated_at=v.updated_at.isoformat() if v.updated_at else "",
            change_reason=v.change_reason,
        )
        for v in versions
    ]


@router.post("/{agent_id}/wiki", response_model=WikiEntryResponse, status_code=status.HTTP_201_CREATED)
async def create_wiki_entry(
    agent_id: str,
    body: WikiEntryCreate,
    request: Request,
    session: DbSession,
) -> WikiEntryResponse:
    agent = await _get_agent_and_verify(agent_id, request, session)
    user_id = getattr(request.state, "user_id", None)
    repo = WikiRepository(session)

    data = body.model_dump()
    data["agent_id"] = agent.id
    data["user_id"] = user_id
    data["created_by"] = "user" if user_id else "agent"

    # Convert trade_ref_ids strings to UUIDs
    raw_refs = data.pop("trade_ref_ids", [])
    parsed_refs = []
    for r in raw_refs:
        try:
            parsed_refs.append(uuid.UUID(str(r)))
        except ValueError:
            pass
    data["trade_ref_ids"] = parsed_refs

    entry = await repo.create_entry(data)
    await session.commit()
    await session.refresh(entry)
    return _serialize_entry(entry)


@router.patch("/{agent_id}/wiki/{entry_id}", response_model=WikiEntryResponse)
async def update_wiki_entry(
    agent_id: str,
    entry_id: str,
    body: WikiEntryUpdate,
    request: Request,
    session: DbSession,
) -> WikiEntryResponse:
    agent = await _get_agent_and_verify(agent_id, request, session)
    user_id = getattr(request.state, "user_id", None)
    repo = WikiRepository(session)

    try:
        entry_uuid = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id format")

    entry = await repo.get_entry(entry_uuid, agent.id)
    if not entry:
        raise HTTPException(status_code=404, detail="Wiki entry not found")

    update_data = {k: v for k, v in body.model_dump().items() if v is not None}
    updated_by = "user" if user_id else "agent"
    entry = await repo.update_entry(entry, update_data, updated_by=updated_by)
    await session.commit()
    await session.refresh(entry)
    return _serialize_entry(entry)


@router.delete("/{agent_id}/wiki/{entry_id}", status_code=status.HTTP_200_OK)
async def delete_wiki_entry(
    agent_id: str,
    entry_id: str,
    request: Request,
    session: DbSession,
) -> dict:
    agent = await _get_agent_and_verify(agent_id, request, session)
    repo = WikiRepository(session)

    try:
        entry_uuid = uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid entry_id format")

    entry = await repo.get_entry(entry_uuid, agent.id)
    if not entry:
        raise HTTPException(status_code=404, detail="Wiki entry not found")

    await repo.soft_delete(entry)
    await session.commit()
    return {"status": "deleted", "id": str(entry.id)}


# ---------------------------------------------------------------------------
# Phoenix Brain endpoint  (brain_router: /api/v2/brain)
# ---------------------------------------------------------------------------


@brain_router.get("/wiki", response_model=WikiListResponse)
async def list_brain_wiki(
    session: DbSession,
    category: str | None = Query(None),
    symbol: str | None = Query(None),
    search: str | None = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
) -> WikiListResponse:
    """Phoenix Brain — all is_shared=True entries across all agents."""
    repo = WikiRepository(session)
    skip = (page - 1) * per_page
    entries, total = await repo.list_shared_entries(
        category=category,
        symbol=symbol,
        search=search,
        min_confidence=min_confidence,
        skip=skip,
        limit=per_page,
    )
    return WikiListResponse(
        entries=[_serialize_entry(e) for e in entries],
        total=total,
        page=page,
        per_page=per_page,
    )
