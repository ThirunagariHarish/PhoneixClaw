"""Agent Gateway — manages Claude Code agents on remote VPS instances."""

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import UUID

from cryptography.fernet import Fernet

from apps.api.src.services.ssh_pool import SSHResult, ssh_pool

logger = logging.getLogger(__name__)

ENCRYPTION_KEY = os.getenv("CREDENTIAL_ENCRYPTION_KEY", "")
AGENTS_DIR = Path(__file__).resolve().parents[4] / "agents"


def _decrypt(value: str) -> str:
    if not value or not ENCRYPTION_KEY:
        return value
    try:
        f = Fernet(ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY)
        return f.decrypt(value.encode()).decode()
    except Exception:
        return value


def _encrypt(value: str) -> str:
    if not ENCRYPTION_KEY:
        return value
    f = Fernet(ENCRYPTION_KEY.encode() if isinstance(ENCRYPTION_KEY, str) else ENCRYPTION_KEY)
    return f.encrypt(value.encode()).decode()


@dataclass
class HealthStatus:
    reachable: bool
    claude_installed: bool
    claude_version: Optional[str] = None
    python_installed: bool = False
    memory_total_mb: int = 0
    memory_used_mb: int = 0
    memory_free_mb: int = 0
    disk_free: str = ""
    cpu_cores: int = 0
    active_agents: list[str] = None

    def __post_init__(self):
        if self.active_agents is None:
            self.active_agents = []


@dataclass
class AgentInfo:
    name: str
    path: str
    status: str


class AgentGateway:
    """Manages Claude Code agents on remote VPS instances via SSH."""

    def _write_temp_key(self, encrypted_key: str) -> str:
        key_content: str
        try:
            from shared.crypto.credentials import decrypt_credentials

            creds = decrypt_credentials(encrypted_key)
            if isinstance(creds, dict) and creds.get("ssh_key"):
                key_content = creds["ssh_key"]
            else:
                key_content = _decrypt(encrypted_key)
        except Exception:
            key_content = _decrypt(encrypted_key)
        fd, path = tempfile.mkstemp(prefix="phoenix_ssh_", suffix=".key")
        with os.fdopen(fd, "w") as f:
            f.write(key_content)
            if not key_content.endswith("\n"):
                f.write("\n")
        os.chmod(path, 0o600)
        return path

    def register_instance(self, instance_id: UUID, host: str, port: int, username: str, encrypted_key: str):
        key_path = self._write_temp_key(encrypted_key)
        ssh_pool.register(instance_id, host, port, username, key_path)

    def unregister_instance(self, instance_id: UUID):
        ssh_pool.unregister(instance_id)

    async def check_health(self, instance_id: UUID) -> HealthStatus:
        result = await ssh_pool.run(instance_id, "echo REACHABLE")
        if result.exit_code != 0 or "REACHABLE" not in result.stdout:
            return HealthStatus(reachable=False, claude_installed=False)

        claude_result = await ssh_pool.run(instance_id, "claude --version 2>/dev/null || echo NOT_INSTALLED")
        claude_installed = "NOT_INSTALLED" not in claude_result.stdout
        claude_version = claude_result.stdout.strip() if claude_installed else None

        python_result = await ssh_pool.run(instance_id, "python3 --version 2>/dev/null || echo NOT_INSTALLED")
        python_installed = "NOT_INSTALLED" not in python_result.stdout

        mem_result = await ssh_pool.run(instance_id, "free -m 2>/dev/null | awk '/Mem:/{print $2,$3,$4}' || echo '0 0 0'")
        parts = mem_result.stdout.strip().split()
        mem_total = int(parts[0]) if len(parts) >= 3 else 0
        mem_used = int(parts[1]) if len(parts) >= 3 else 0
        mem_free = int(parts[2]) if len(parts) >= 3 else 0

        disk_result = await ssh_pool.run(instance_id, "df -h ~ 2>/dev/null | awk 'NR==2{print $4}' || echo '?'")
        cpu_result = await ssh_pool.run(instance_id, "nproc 2>/dev/null || echo '1'")

        agents_result = await ssh_pool.run(instance_id, "ls ~/agents/live/ 2>/dev/null || echo NONE")
        agents = [] if "NONE" in agents_result.stdout else agents_result.stdout.strip().split()

        return HealthStatus(
            reachable=True,
            claude_installed=claude_installed,
            claude_version=claude_version,
            python_installed=python_installed,
            memory_total_mb=mem_total,
            memory_used_mb=mem_used,
            memory_free_mb=mem_free,
            disk_free=disk_result.stdout.strip(),
            cpu_cores=int(cpu_result.stdout.strip()),
            active_agents=agents,
        )

    async def install_claude_code(self, instance_id: UUID) -> SSHResult:
        return await ssh_pool.run(
            instance_id,
            "curl -fsSL https://claude.ai/install.sh | sh && claude --version",
            timeout=600,
        )

    async def ship_agent(self, instance_id: UUID, agent_type: str, config: dict) -> SSHResult:
        local_path = str(AGENTS_DIR / agent_type)
        if not os.path.isdir(local_path):
            return SSHResult(exit_code=1, stdout="", stderr=f"Agent type '{agent_type}' not found at {local_path}")

        remote_path = f"~/agents/{agent_type}/"
        await ssh_pool.run(instance_id, f"mkdir -p {remote_path}")

        scp_result = await ssh_pool.scp_to(instance_id, local_path, "~/agents/")
        if scp_result.exit_code != 0:
            return scp_result

        config_json = json.dumps(config, default=str)
        escaped = config_json.replace("'", "'\\''")
        await ssh_pool.run(instance_id, f"echo '{escaped}' > {remote_path}config.json")

        return SSHResult(exit_code=0, stdout=f"Agent shipped to {remote_path}", stderr="")

    async def run_backtesting(self, instance_id: UUID, config: dict) -> SSHResult:
        await self.ship_agent(instance_id, "backtesting", config)
        command = (
            "cd ~/agents/backtesting && "
            "claude --print 'Read config.json and run the backtesting pipeline. "
            "Report progress as JSON lines to stdout.'"
        )
        return await ssh_pool.run(instance_id, command, timeout=7200)

    async def list_agents(self, instance_id: UUID) -> list[AgentInfo]:
        result = await ssh_pool.run(instance_id, "ls -1 ~/agents/live/ 2>/dev/null || echo ''")
        if result.exit_code != 0 or not result.stdout.strip():
            return []
        return [
            AgentInfo(name=name, path=f"~/agents/live/{name}", status="unknown")
            for name in result.stdout.strip().split("\n")
            if name
        ]

    async def send_message(self, instance_id: UUID, agent_name: str, message: str) -> str:
        escaped = message.replace("'", "'\\''")
        result = await ssh_pool.run(
            instance_id,
            f"cd ~/agents/live/{agent_name} && claude --print '{escaped}'",
            timeout=120,
        )
        return result.stdout if result.exit_code == 0 else f"Error: {result.stderr}"

    async def get_agent_logs(self, instance_id: UUID, agent_name: str, lines: int = 100) -> str:
        result = await ssh_pool.run(
            instance_id,
            f"tail -n {lines} ~/agents/live/{agent_name}/trades.log 2>/dev/null || echo 'No logs'",
        )
        return result.stdout


gateway = AgentGateway()
