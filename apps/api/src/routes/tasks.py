"""
Task Board API — kanban tasks, agent roles, task management.

M3.4: Task Board and Agent Roles.
Reference: PRD Section 10.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.engine import get_session
from shared.db.models.task import Task

router = APIRouter(prefix="/api/v2/tasks", tags=["tasks"])

AGENT_ROLE_TEMPLATES = [
    {"id": "day-trader", "name": "Day Trader", "description": "Intraday trading specialist"},
    {"id": "technical-analyst", "name": "Technical Analyst", "description": "Chart pattern and indicator expert"},
    {"id": "risk-analyzer", "name": "Risk Analyzer", "description": "Portfolio risk assessment specialist"},
    {"id": "market-researcher", "name": "Market Researcher", "description": "Fundamental and macro analysis"},
    {"id": "options-specialist", "name": "Options Specialist", "description": "Options flow and Greeks analysis"},
    {"id": "sentiment-analyst", "name": "Sentiment Analyst", "description": "Social media and news sentiment"},
    {"id": "quant-developer", "name": "Quant Developer", "description": "Algorithm and model development"},
    {"id": "compliance-officer", "name": "Compliance Officer", "description": "Regulatory and risk compliance"},
]


def _parse_task_id(task_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="Task not found") from e


def _skills_from_labels(labels: Any) -> list[str]:
    if isinstance(labels, list):
        return labels
    if isinstance(labels, dict):
        s = labels.get("skills")
        return list(s) if isinstance(s, list) else []
    return []


def _task_to_response(t: Task) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "title": t.title,
        "description": t.description or "",
        "assigned_agent_id": str(t.agent_id) if t.agent_id else None,
        "agent_role": t.agent_role,
        "status": t.status,
        "priority": t.priority,
        "skills": _skills_from_labels(t.labels),
        "created_at": t.created_at.isoformat() if t.created_at else "",
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "completed_at": t.completed_at.isoformat() if t.completed_at else None,
    }


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    assigned_agent_id: str | None = None
    agent_role: str | None = None
    status: str = "TODO"
    priority: str = "medium"
    skills: list[str] = Field(default_factory=list)


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    assigned_agent_id: str | None = None
    priority: str | None = None
    skills: list[str] | None = None


@router.get("/roles")
async def list_roles(_session: AsyncSession = Depends(get_session)):
    return AGENT_ROLE_TEMPLATES


@router.get("")
async def list_tasks(
    status_filter: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Task).order_by(Task.created_at.desc())
    if status_filter:
        stmt = stmt.where(Task.status == status_filter)
    result = await session.execute(stmt)
    rows = result.scalars().all()
    return [_task_to_response(t) for t in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    session: AsyncSession = Depends(get_session),
):
    agent_id: uuid.UUID | None = None
    if payload.assigned_agent_id:
        try:
            agent_id = uuid.UUID(payload.assigned_agent_id)
        except ValueError as e:
            raise HTTPException(status_code=422, detail="Invalid assigned_agent_id") from e

    labels: dict[str, Any] = {"skills": payload.skills} if payload.skills else {}
    task = Task(
        title=payload.title,
        description=payload.description or None,
        agent_id=agent_id,
        agent_role=payload.agent_role,
        status=payload.status,
        priority=payload.priority,
        labels=labels,
    )
    session.add(task)
    await session.flush()
    return _task_to_response(task)


@router.patch("/{task_id}")
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    session: AsyncSession = Depends(get_session),
):
    tid = _parse_task_id(task_id)
    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    data = payload.model_dump(exclude_unset=True)
    if "title" in data:
        task.title = data["title"]
    if "description" in data:
        task.description = data["description"] or None
    if "status" in data:
        task.status = data["status"]
    if "assigned_agent_id" in data:
        aid = data["assigned_agent_id"]
        if aid is None:
            task.agent_id = None
        else:
            try:
                task.agent_id = uuid.UUID(aid)
            except ValueError as e:
                raise HTTPException(status_code=422, detail="Invalid assigned_agent_id") from e
    if "priority" in data:
        task.priority = data["priority"]
    if "skills" in data and data["skills"] is not None:
        task.labels = {"skills": data["skills"]}
    await session.flush()
    return _task_to_response(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
):
    tid = _parse_task_id(task_id)
    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    await session.delete(task)


class TaskMove(BaseModel):
    status: str = Field(..., pattern="^(BACKLOG|IN_PROGRESS|UNDER_REVIEW|COMPLETED)$")


@router.patch("/{task_id}/move")
async def move_task(
    task_id: str,
    payload: TaskMove,
    session: AsyncSession = Depends(get_session),
):
    """Move a task between Kanban columns."""
    tid = _parse_task_id(task_id)
    task = await session.get(Task, tid)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    old_status = task.status
    task.status = payload.status
    now = datetime.now(timezone.utc)
    if payload.status == "IN_PROGRESS" and not task.started_at:
        task.started_at = now
    if payload.status == "COMPLETED":
        task.completed_at = now
    await session.flush()
    return {"id": task_id, "old_status": old_status, "new_status": payload.status}
