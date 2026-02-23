import logging
import uuid
from datetime import datetime
from datetime import timezone as tz

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.database import get_session
from shared.models.trade import BoardTask, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/board", tags=["board"])

VALID_STATUSES = {"refinement", "ready", "in_progress", "completed"}
VALID_PRIORITIES = {"critical", "high", "medium", "low"}


def _require_admin(request: Request) -> str:
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return request.state.user_id


class TaskCreate(BaseModel):
    title: str
    description: str | None = None
    status: str = "refinement"
    priority: str = "medium"
    assigned_to: str | None = None
    labels: list[str] = []
    due_date: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    assigned_to: str | None = None
    labels: list[str] | None = None
    due_date: str | None = None
    status: str | None = None


class TaskMove(BaseModel):
    status: str
    position: int


class TaskResponse(BaseModel):
    id: str
    title: str
    description: str | None
    status: str
    priority: str
    position: int
    created_by: str
    created_by_name: str | None = None
    assigned_to: str | None
    assigned_to_name: str | None = None
    labels: list[str] = []
    due_date: str | None = None
    created_at: str
    updated_at: str


class UserBrief(BaseModel):
    id: str
    name: str | None
    email: str


async def _resolve_users(session: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not user_ids:
        return {}
    result = await session.execute(select(User).where(User.id.in_(user_ids)))
    return {u.id: u for u in result.scalars().all()}


def _task_response(t: BoardTask, user_map: dict | None = None) -> dict:
    user_map = user_map or {}
    creator = user_map.get(t.created_by)
    assignee = user_map.get(t.assigned_to) if t.assigned_to else None
    return {
        "id": str(t.id),
        "title": t.title,
        "description": t.description,
        "status": t.status,
        "priority": t.priority,
        "position": t.position,
        "created_by": str(t.created_by),
        "created_by_name": (creator.name or creator.email) if creator else None,
        "assigned_to": str(t.assigned_to) if t.assigned_to else None,
        "assigned_to_name": (assignee.name or assignee.email) if assignee else None,
        "labels": t.labels or [],
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "created_at": t.created_at.isoformat() if t.created_at else "",
        "updated_at": t.updated_at.isoformat() if t.updated_at else "",
    }


@router.get("/users", response_model=list[UserBrief])
async def list_users(
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: str = Depends(_require_admin),
):
    result = await session.execute(select(User).where(User.is_active.is_(True)).order_by(User.name))
    return [{"id": str(u.id), "name": u.name, "email": u.email} for u in result.scalars().all()]


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: str = Depends(_require_admin),
):
    result = await session.execute(
        select(BoardTask).order_by(BoardTask.status, BoardTask.position)
    )
    tasks = result.scalars().all()
    user_ids: set[uuid.UUID] = set()
    for t in tasks:
        user_ids.add(t.created_by)
        if t.assigned_to:
            user_ids.add(t.assigned_to)
    user_map = await _resolve_users(session, user_ids)
    return [_task_response(t, user_map) for t in tasks]


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: str = Depends(_require_admin),
):
    result = await session.execute(
        select(BoardTask).where(BoardTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    user_ids = {task.created_by}
    if task.assigned_to:
        user_ids.add(task.assigned_to)
    user_map = await _resolve_users(session, user_ids)
    return _task_response(task, user_map)


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    req: TaskCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: str = Depends(_require_admin),
):
    if req.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {req.status}")
    if req.priority not in VALID_PRIORITIES:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {req.priority}")

    max_pos = await session.execute(
        select(BoardTask.position)
        .where(BoardTask.status == req.status)
        .order_by(BoardTask.position.desc())
        .limit(1)
    )
    next_pos = (max_pos.scalar() or 0) + 1

    due = None
    if req.due_date:
        raw = req.due_date
        due = (
            datetime.fromisoformat(raw).replace(tzinfo=tz.utc)
            if "T" in raw
            else datetime.fromisoformat(raw + "T00:00:00").replace(tzinfo=tz.utc)
        )

    task = BoardTask(
        title=req.title,
        description=req.description,
        status=req.status,
        priority=req.priority,
        position=next_pos,
        created_by=uuid.UUID(admin_id),
        assigned_to=uuid.UUID(req.assigned_to) if req.assigned_to else None,
        labels=req.labels,
        due_date=due,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    user_map = await _resolve_users(session, {task.created_by} | ({task.assigned_to} if task.assigned_to else set()))
    return _task_response(task, user_map)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    req: TaskUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: str = Depends(_require_admin),
):
    result = await session.execute(
        select(BoardTask).where(BoardTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if req.title is not None:
        task.title = req.title
    if req.description is not None:
        task.description = req.description
    if req.priority is not None:
        if req.priority not in VALID_PRIORITIES:
            raise HTTPException(status_code=400, detail=f"Invalid priority: {req.priority}")
        task.priority = req.priority
    if req.assigned_to is not None:
        task.assigned_to = uuid.UUID(req.assigned_to) if req.assigned_to else None
    if req.labels is not None:
        task.labels = req.labels
    if req.due_date is not None:
        if req.due_date == "":
            task.due_date = None
        else:
            task.due_date = (
                datetime.fromisoformat(req.due_date).replace(tzinfo=tz.utc)
                if "T" in req.due_date
                else datetime.fromisoformat(req.due_date + "T00:00:00").replace(tzinfo=tz.utc)
            )
    if req.status is not None:
        if req.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {req.status}")
        task.status = req.status

    await session.commit()
    await session.refresh(task)
    user_ids = {task.created_by}
    if task.assigned_to:
        user_ids.add(task.assigned_to)
    user_map = await _resolve_users(session, user_ids)
    return _task_response(task, user_map)


@router.patch("/{task_id}/move", response_model=TaskResponse)
async def move_task(
    task_id: str,
    req: TaskMove,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: str = Depends(_require_admin),
):
    if req.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {req.status}")

    result = await session.execute(
        select(BoardTask).where(BoardTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    old_status = task.status

    if old_status != req.status:
        await session.execute(
            update(BoardTask)
            .where(BoardTask.status == old_status, BoardTask.position > task.position)
            .values(position=BoardTask.position - 1)
        )

    await session.execute(
        update(BoardTask)
        .where(
            BoardTask.status == req.status,
            BoardTask.position >= req.position,
            BoardTask.id != task.id,
        )
        .values(position=BoardTask.position + 1)
    )

    task.status = req.status
    task.position = req.position

    await session.commit()
    await session.refresh(task)
    user_ids = {task.created_by}
    if task.assigned_to:
        user_ids.add(task.assigned_to)
    user_map = await _resolve_users(session, user_ids)
    return _task_response(task, user_map)


@router.delete("/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    admin_id: str = Depends(_require_admin),
):
    result = await session.execute(
        select(BoardTask).where(BoardTask.id == uuid.UUID(task_id))
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    await session.execute(
        update(BoardTask)
        .where(BoardTask.status == task.status, BoardTask.position > task.position)
        .values(position=BoardTask.position - 1)
    )

    await session.delete(task)
    await session.commit()
