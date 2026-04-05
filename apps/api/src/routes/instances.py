"""Claude Code instance management API routes."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from apps.api.src.deps import DbSession
from shared.db.models.claude_code_instance import ClaudeCodeInstance

router = APIRouter(prefix="/api/v2/instances", tags=["instances"])


class InstanceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    host: str = Field(..., min_length=1)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    ssh_username: str = Field(default="root")
    ssh_private_key: str = Field(..., min_length=10)
    role: str = Field(default="general", pattern="^(backtesting|trading|general)$")
    node_type: str = Field(default="vps", pattern="^(vps|local)$")


class InstanceUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    status: str | None = None


class InstanceResponse(BaseModel):
    id: str
    name: str
    host: str
    ssh_port: int
    ssh_username: str
    role: str
    status: str
    node_type: str
    capabilities: dict[str, Any]
    claude_version: str | None
    agent_count: int
    last_heartbeat_at: str | None
    created_at: str

    @classmethod
    def from_model(cls, inst: ClaudeCodeInstance) -> "InstanceResponse":
        return cls(
            id=str(inst.id),
            name=inst.name,
            host=inst.host,
            ssh_port=inst.ssh_port,
            ssh_username=inst.ssh_username,
            role=inst.role,
            status=inst.status,
            node_type=inst.node_type,
            capabilities=inst.capabilities or {},
            claude_version=inst.claude_version,
            agent_count=inst.agent_count,
            last_heartbeat_at=inst.last_heartbeat_at.isoformat() if inst.last_heartbeat_at else None,
            created_at=inst.created_at.isoformat() if inst.created_at else "",
        )


@router.get("", response_model=list[InstanceResponse])
async def list_instances(session: DbSession, role: str | None = None):
    query = select(ClaudeCodeInstance).order_by(desc(ClaudeCodeInstance.created_at))
    if role:
        query = query.where(ClaudeCodeInstance.role == role)
    result = await session.execute(query)
    return [InstanceResponse.from_model(i) for i in result.scalars().all()]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=InstanceResponse)
async def create_instance(payload: InstanceCreate, session: DbSession):
    from shared.crypto.credentials import encrypt_credentials

    encrypted_key = encrypt_credentials({"ssh_key": payload.ssh_private_key})

    instance = ClaudeCodeInstance(
        id=uuid.uuid4(),
        name=payload.name,
        host=payload.host,
        ssh_port=payload.ssh_port,
        ssh_username=payload.ssh_username,
        ssh_key_encrypted=encrypted_key,
        role=payload.role,
        node_type=payload.node_type,
        status="ONLINE",
    )
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    return InstanceResponse.from_model(instance)


class VerifyInstanceRequest(BaseModel):
    host: str
    ssh_port: int = 22
    ssh_username: str = "root"
    ssh_private_key: str


@router.post("/verify")
async def verify_instance(payload: VerifyInstanceRequest):
    """Test SSH connectivity and check Claude Code installation without saving."""
    from apps.api.src.services.agent_gateway import gateway
    from shared.crypto.credentials import encrypt_credentials

    temp_id = uuid.uuid4()

    encrypted = encrypt_credentials({"ssh_key": payload.ssh_private_key})

    gateway.register_instance(temp_id, payload.host, payload.ssh_port, payload.ssh_username, encrypted)
    try:
        health = await gateway.check_health(temp_id)
        return {
            "reachable": health.reachable,
            "claude_installed": health.claude_installed,
            "claude_version": health.claude_version,
            "python_installed": health.python_installed,
            "memory_free_mb": health.memory_free_mb,
            "disk_free": health.disk_free,
        }
    finally:
        gateway.unregister_instance(temp_id)


@router.get("/{instance_id}", response_model=InstanceResponse)
async def get_instance(instance_id: str, session: DbSession):
    result = await session.execute(
        select(ClaudeCodeInstance).where(ClaudeCodeInstance.id == uuid.UUID(instance_id))
    )
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    return InstanceResponse.from_model(inst)


@router.patch("/{instance_id}", response_model=InstanceResponse)
async def update_instance(instance_id: str, payload: InstanceUpdate, session: DbSession):
    result = await session.execute(
        select(ClaudeCodeInstance).where(ClaudeCodeInstance.id == uuid.UUID(instance_id))
    )
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    if payload.name is not None:
        inst.name = payload.name
    if payload.role is not None:
        inst.role = payload.role
    if payload.status is not None:
        inst.status = payload.status
    inst.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(inst)
    return InstanceResponse.from_model(inst)


@router.delete("/{instance_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_instance(instance_id: str, session: DbSession):
    result = await session.execute(
        select(ClaudeCodeInstance).where(ClaudeCodeInstance.id == uuid.UUID(instance_id))
    )
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")
    await session.delete(inst)
    await session.commit()


@router.post("/{instance_id}/check")
async def check_instance(instance_id: str, session: DbSession):
    """SSH-based health check."""
    result = await session.execute(
        select(ClaudeCodeInstance).where(ClaudeCodeInstance.id == uuid.UUID(instance_id))
    )
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")

    from apps.api.src.services.agent_gateway import gateway

    gateway.register_instance(inst.id, inst.host, inst.ssh_port, inst.ssh_username, inst.ssh_key_encrypted)

    health = await gateway.check_health(inst.id)

    inst.status = "ONLINE" if health.reachable else "OFFLINE"
    inst.claude_version = health.claude_version
    inst.capabilities = {
        "python_installed": health.python_installed,
        "memory_total_mb": health.memory_total_mb,
        "memory_used_mb": health.memory_used_mb,
        "memory_free_mb": health.memory_free_mb,
        "disk_free": health.disk_free,
        "cpu_cores": health.cpu_cores,
    }
    inst.agent_count = len(health.active_agents)
    inst.last_heartbeat_at = datetime.now(timezone.utc)
    await session.commit()

    return {
        "reachable": health.reachable,
        "claude_installed": health.claude_installed,
        "claude_version": health.claude_version,
        "python_installed": health.python_installed,
        "memory_free_mb": health.memory_free_mb,
        "disk_free": health.disk_free,
        "active_agents": health.active_agents,
    }


@router.post("/{instance_id}/install-claude")
async def install_claude(instance_id: str, session: DbSession):
    """Install Claude Code on the VPS instance."""
    result = await session.execute(
        select(ClaudeCodeInstance).where(ClaudeCodeInstance.id == uuid.UUID(instance_id))
    )
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")

    from apps.api.src.services.agent_gateway import gateway

    gateway.register_instance(inst.id, inst.host, inst.ssh_port, inst.ssh_username, inst.ssh_key_encrypted)

    inst.status = "PROVISIONING"
    await session.commit()

    ssh_result = await gateway.install_claude_code(inst.id)

    if ssh_result.exit_code == 0:
        inst.status = "ONLINE"
        inst.claude_version = ssh_result.stdout.strip().split("\n")[-1]
    else:
        inst.status = "ERROR"

    await session.commit()
    return {"success": ssh_result.exit_code == 0, "output": ssh_result.stdout, "error": ssh_result.stderr}


class SetupClaudeRequest(BaseModel):
    anthropic_api_key: str = Field(..., min_length=10)


@router.post("/{instance_id}/setup-claude")
async def setup_claude(instance_id: str, payload: SetupClaudeRequest, session: DbSession):
    """Install Claude Code on VPS and authenticate with the Anthropic API key.

    Steps:
    1. Install Claude Code CLI via official installer
    2. Set ANTHROPIC_API_KEY in the shell profile so Claude Code can authenticate
    3. Verify claude --version works
    """
    result = await session.execute(
        select(ClaudeCodeInstance).where(ClaudeCodeInstance.id == uuid.UUID(instance_id))
    )
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")

    from apps.api.src.services.agent_gateway import gateway

    gateway.register_instance(inst.id, inst.host, inst.ssh_port, inst.ssh_username, inst.ssh_key_encrypted)

    inst.status = "PROVISIONING"
    await session.commit()

    steps_log: list[dict] = []

    install_result = await gateway.install_claude_code(inst.id)
    steps_log.append({
        "step": "install",
        "success": install_result.exit_code == 0,
        "output": install_result.stdout[-500:] if install_result.stdout else "",
        "error": install_result.stderr[-500:] if install_result.stderr else "",
    })

    if install_result.exit_code != 0:
        inst.status = "ERROR"
        await session.commit()
        return {
            "success": False,
            "step_failed": "install",
            "steps": steps_log,
        }

    api_key = payload.anthropic_api_key
    escaped_key = api_key.replace("'", "'\\''")
    auth_cmd = (
        f"export PATH=\"$HOME/.claude/bin:$HOME/.local/bin:$PATH\"; "
        f"grep -q 'ANTHROPIC_API_KEY' ~/.bashrc 2>/dev/null && "
        f"sed -i 's|^export ANTHROPIC_API_KEY=.*|export ANTHROPIC_API_KEY=\\'{escaped_key}\\'|' ~/.bashrc || "
        f"echo 'export ANTHROPIC_API_KEY=\\'{escaped_key}\\'' >> ~/.bashrc; "
        f"grep -q '.claude/bin' ~/.bashrc 2>/dev/null || "
        f"echo 'export PATH=\"$HOME/.claude/bin:$PATH\"' >> ~/.bashrc; "
        f"export ANTHROPIC_API_KEY='{escaped_key}'; "
        f"claude --version"
    )
    auth_result = await gateway.run_command(inst.id, auth_cmd)
    steps_log.append({
        "step": "authenticate",
        "success": auth_result.exit_code == 0,
        "output": auth_result.stdout[-500:] if auth_result.stdout else "",
    })

    if auth_result.exit_code == 0:
        inst.status = "ONLINE"
        inst.claude_version = auth_result.stdout.strip().split("\n")[-1]
    else:
        inst.status = "ERROR"

    inst.last_heartbeat_at = datetime.now(timezone.utc)
    await session.commit()

    return {
        "success": auth_result.exit_code == 0,
        "claude_version": inst.claude_version,
        "steps": steps_log,
    }


@router.post("/{instance_id}/ship-agent")
async def ship_agent(instance_id: str, session: DbSession, agent_type: str = "backtesting"):
    """Ship a backtesting agent to the VPS instance."""
    result = await session.execute(
        select(ClaudeCodeInstance).where(ClaudeCodeInstance.id == uuid.UUID(instance_id))
    )
    inst = result.scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instance not found")

    from apps.api.src.services.agent_gateway import gateway

    gateway.register_instance(inst.id, inst.host, inst.ssh_port, inst.ssh_username, inst.ssh_key_encrypted)

    ssh_result = await gateway.ship_agent(inst.id, agent_type, {})

    return {"success": ssh_result.exit_code == 0, "output": ssh_result.stdout, "error": ssh_result.stderr}
