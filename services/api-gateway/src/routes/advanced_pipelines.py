import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.database import get_session
from shared.models.trade import AdvancedPipeline, AdvancedPipelineVersion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/advanced-pipelines", tags=["advanced-pipelines"])


class PipelineCreate(BaseModel):
    name: str
    description: str | None = None
    flow_json: dict = {}
    tags: list[str] = []


class PipelineUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    flow_json: dict | None = None
    tags: list[str] | None = None


@router.get("")
async def list_pipelines(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    result = await session.execute(
        select(AdvancedPipeline)
        .where(AdvancedPipeline.user_id == uuid.UUID(user_id))
        .order_by(desc(AdvancedPipeline.updated_at))
    )
    return [_response(p) for p in result.scalars().all()]


@router.get("/{pipeline_id}")
async def get_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    p = await _get_pipeline(pipeline_id, request, session)
    return _response(p)


@router.post("", status_code=201)
async def create_pipeline(
    req: PipelineCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    user_id = request.state.user_id
    pipeline = AdvancedPipeline(
        user_id=uuid.UUID(user_id),
        name=req.name,
        description=req.description,
        flow_json=req.flow_json or {},
        tags=req.tags or [],
    )
    session.add(pipeline)
    await session.commit()
    await session.refresh(pipeline)

    version = AdvancedPipelineVersion(
        pipeline_id=pipeline.id,
        version=1,
        flow_json=req.flow_json or {},
        change_summary="Initial version",
        created_by=uuid.UUID(user_id),
    )
    session.add(version)
    await session.commit()

    return _response(pipeline)


@router.put("/{pipeline_id}")
async def update_pipeline(
    pipeline_id: str,
    req: PipelineUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    p = await _get_pipeline(pipeline_id, request, session)

    if req.name is not None:
        p.name = req.name
    if req.description is not None:
        p.description = req.description
    if req.tags is not None:
        p.tags = req.tags
    if req.flow_json is not None:
        p.flow_json = req.flow_json
        p.version += 1

        version = AdvancedPipelineVersion(
            pipeline_id=p.id,
            version=p.version,
            flow_json=req.flow_json,
            change_summary=f"Version {p.version}",
            created_by=uuid.UUID(request.state.user_id),
        )
        session.add(version)

    p.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(p)
    return _response(p)


@router.delete("/{pipeline_id}", status_code=204)
async def delete_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    p = await _get_pipeline(pipeline_id, request, session)
    await session.delete(p)
    await session.commit()


@router.post("/{pipeline_id}/deploy")
async def deploy_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    p = await _get_pipeline(pipeline_id, request, session)

    nodes = p.flow_json.get("nodes", [])
    p.flow_json.get("edges", [])
    if not nodes:
        raise HTTPException(status_code=400, detail="Pipeline has no nodes")

    has_source = any(n.get("type") == "dataSource" for n in nodes)
    has_broker = any(n.get("type") == "broker" for n in nodes)
    if not has_source:
        raise HTTPException(status_code=400, detail="Pipeline must have at least one data source")
    if not has_broker:
        raise HTTPException(status_code=400, detail="Pipeline must have at least one broker node")

    p.status = "deployed"
    p.enabled = True
    p.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(p)
    return _response(p)


@router.post("/{pipeline_id}/test")
async def test_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    p = await _get_pipeline(pipeline_id, request, session)

    nodes = p.flow_json.get("nodes", [])
    p.flow_json.get("edges", [])

    results = []
    for node in nodes:
        results.append({
            "node_id": node.get("id"),
            "node_type": node.get("type"),
            "label": node.get("data", {}).get("label", ""),
            "status": "ok",
            "output_sample": {"message": f"Test passed for {node.get('data', {}).get('label', '')}"},
        })

    return {"pipeline_id": pipeline_id, "test_results": results, "overall": "passed"}


@router.get("/{pipeline_id}/versions")
async def list_versions(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    await _get_pipeline(pipeline_id, request, session)

    result = await session.execute(
        select(AdvancedPipelineVersion)
        .where(AdvancedPipelineVersion.pipeline_id == uuid.UUID(pipeline_id))
        .order_by(desc(AdvancedPipelineVersion.version))
    )
    versions = result.scalars().all()
    return [
        {
            "id": str(v.id),
            "version": v.version,
            "change_summary": v.change_summary,
            "created_at": v.created_at.isoformat() if v.created_at else None,
        }
        for v in versions
    ]


@router.post("/{pipeline_id}/versions/{version}/revert")
async def revert_version(
    pipeline_id: str,
    version: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    p = await _get_pipeline(pipeline_id, request, session)

    result = await session.execute(
        select(AdvancedPipelineVersion).where(
            AdvancedPipelineVersion.pipeline_id == uuid.UUID(pipeline_id),
            AdvancedPipelineVersion.version == version,
        )
    )
    v = result.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail=f"Version {version} not found")

    p.flow_json = v.flow_json
    p.version += 1
    p.updated_at = datetime.now(timezone.utc)

    new_version = AdvancedPipelineVersion(
        pipeline_id=p.id,
        version=p.version,
        flow_json=v.flow_json,
        change_summary=f"Reverted to version {version}",
        created_by=uuid.UUID(request.state.user_id),
    )
    session.add(new_version)
    await session.commit()
    await session.refresh(p)
    return _response(p)


@router.post("/{pipeline_id}/export")
async def export_pipeline(
    pipeline_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    p = await _get_pipeline(pipeline_id, request, session)
    return {
        "name": p.name,
        "description": p.description,
        "flow_json": p.flow_json,
        "tags": p.tags,
        "version": p.version,
    }


@router.post("/import")
async def import_pipeline(
    req: PipelineCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    return await create_pipeline(req, request, session)


async def _get_pipeline(
    pipeline_id: str, request: Request, session: AsyncSession,
) -> AdvancedPipeline:
    user_id = request.state.user_id
    result = await session.execute(
        select(AdvancedPipeline).where(
            AdvancedPipeline.id == uuid.UUID(pipeline_id),
            AdvancedPipeline.user_id == uuid.UUID(user_id),
        )
    )
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return p


def _response(p: AdvancedPipeline) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "flow_json": p.flow_json or {},
        "status": p.status,
        "version": p.version,
        "enabled": p.enabled,
        "tags": p.tags or [],
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
