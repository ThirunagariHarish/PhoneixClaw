"""
Automations API — cron-scheduled tasks and NL task input.

M3.5: Automation scheduler.
Reference: PRD Section 10.2.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.task import Automation

router = APIRouter(prefix="/api/v2/automations", tags=["automations"])

_DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")

AUTOMATION_TEMPLATES = [
    {"id": "morning-briefing", "name": "Morning Market Briefing", "cron": "0 8 * * 1-5", "description": "Daily pre-market summary"},
    {"id": "eod-report", "name": "End of Day Report", "cron": "0 16 * * 1-5", "description": "Daily P&L and position summary"},
    {"id": "earnings-watch", "name": "Earnings Watch", "cron": "0 7 * * 1-5", "description": "Upcoming earnings alerts"},
    {"id": "options-expiry", "name": "Options Expiry Check", "cron": "0 9 * * 5", "description": "Weekly options expiration review"},
    {"id": "portfolio-rebalance", "name": "Portfolio Rebalance", "cron": "0 10 1 * *", "description": "Monthly portfolio rebalancing"},
    {"id": "risk-report", "name": "Weekly Risk Report", "cron": "0 17 * * 5", "description": "Weekly risk metrics summary"},
]


def _parse_auto_id(auto_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(auto_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Automation not found") from e


def _automation_to_response(a: Automation) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "name": a.name,
        "description": a.description or "",
        "cron_expression": a.cron_expression,
        "task_prompt": a.natural_language or "",
        "delivery_channel": a.delivery_channel,
        "target_instance_id": str(a.instance_id) if a.instance_id else None,
        "is_active": a.is_active,
        "last_run": a.last_run_at.isoformat() if a.last_run_at else None,
        "next_run": a.next_run_at.isoformat() if a.next_run_at else None,
        "run_count": a.run_count,
        "created_at": a.created_at.isoformat() if a.created_at else "",
    }


def _parse_instance_id(value: str | None) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="Invalid target_instance_id") from e


class AutomationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    cron_expression: str = "0 8 * * 1-5"
    task_prompt: str = ""
    delivery_channel: str = "dashboard"
    target_instance_id: str | None = None
    is_active: bool = True


@router.get("/templates")
async def list_templates(_session: AsyncSession = Depends(get_session)):
    return AUTOMATION_TEMPLATES


@router.get("")
async def list_automations(session: AsyncSession = Depends(get_session)):
    stmt = select(Automation).order_by(Automation.created_at.desc())
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_automation_to_response(a) for a in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_automation(
    payload: AutomationCreate,
    session: AsyncSession = Depends(get_session),
):
    instance_id = _parse_instance_id(payload.target_instance_id)
    automation = Automation(
        name=payload.name,
        description=payload.description or None,
        cron_expression=payload.cron_expression,
        natural_language=payload.task_prompt or None,
        delivery_channel=payload.delivery_channel,
        instance_id=instance_id,
        is_active=payload.is_active,
        user_id=_DEFAULT_USER_ID,
        agent_role="automation",
        delivery_config={},
    )
    session.add(automation)
    await session.flush()
    return _automation_to_response(automation)


def _apply_automation_patch(auto: Automation, payload: dict) -> None:
    field_map = {
        "name": "name",
        "description": "description",
        "cron_expression": "cron_expression",
        "task_prompt": "natural_language",
        "delivery_channel": "delivery_channel",
        "target_instance_id": "instance_id",
        "is_active": "is_active",
        "last_run": "last_run_at",
        "next_run": "next_run_at",
        "run_count": "run_count",
    }
    for k, v in payload.items():
        if k in ("id", "created_at"):
            continue
        attr = field_map.get(k)
        if not attr:
            continue
        if k == "target_instance_id":
            if v is None or v == "":
                setattr(auto, "instance_id", None)
            elif isinstance(v, str):
                setattr(auto, "instance_id", _parse_instance_id(v))
            else:
                setattr(auto, "instance_id", v)
        elif k == "task_prompt":
            setattr(auto, attr, (v if v else None) if isinstance(v, str) else v)
        elif k in ("last_run", "next_run"):
            if v is None:
                setattr(auto, attr, None)
            elif isinstance(v, str):
                setattr(auto, attr, datetime.fromisoformat(v.replace("Z", "+00:00")))
            else:
                setattr(auto, attr, v)
        else:
            setattr(auto, attr, v)


@router.patch("/{auto_id}")
async def update_automation(
    auto_id: str,
    payload: dict,
    session: AsyncSession = Depends(get_session),
):
    aid = _parse_auto_id(auto_id)
    auto = await session.get(Automation, aid)
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    _apply_automation_patch(auto, payload)
    await session.flush()
    return _automation_to_response(auto)


@router.delete("/{auto_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation(
    auto_id: str,
    session: AsyncSession = Depends(get_session),
):
    aid = _parse_auto_id(auto_id)
    auto = await session.get(Automation, aid)
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    await session.delete(auto)


@router.post("/{auto_id}/run")
async def trigger_automation(
    auto_id: str,
    session: AsyncSession = Depends(get_session),
):
    aid = _parse_auto_id(auto_id)
    auto = await session.get(Automation, aid)
    if not auto:
        raise HTTPException(status_code=404, detail="Automation not found")
    auto.last_run_at = datetime.now(timezone.utc)
    auto.run_count = (auto.run_count or 0) + 1
    await session.flush()
    return {"status": "triggered", "automation_id": auto_id}
