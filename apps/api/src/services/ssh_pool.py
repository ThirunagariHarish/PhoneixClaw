"""SSH connection pool for communicating with Claude Code VPS instances."""

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID

logger = logging.getLogger(__name__)


@dataclass
class SSHResult:
    exit_code: int
    stdout: str
    stderr: str


class SSHConnectionPool:
    """Manages SSH connections to VPS instances.

    Uses asyncio subprocess for SSH commands rather than asyncssh
    to avoid the extra dependency — the system's ssh binary is reliable
    and supports all key types out of the box.
    """

    def __init__(self):
        self._key_files: dict[UUID, str] = {}
        self._configs: dict[UUID, dict] = {}

    def register(self, instance_id: UUID, host: str, port: int, username: str, key_path: str):
        self._configs[instance_id] = {
            "host": host,
            "port": port,
            "username": username,
        }
        self._key_files[instance_id] = key_path

    def unregister(self, instance_id: UUID):
        self._configs.pop(instance_id, None)
        self._key_files.pop(instance_id, None)

    def _ssh_base_args(self, instance_id: UUID) -> list[str]:
        cfg = self._configs[instance_id]
        key = self._key_files[instance_id]
        return [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=15",
            "-o", "BatchMode=yes",
            "-i", key,
            "-p", str(cfg["port"]),
            f"{cfg['username']}@{cfg['host']}",
        ]

    async def run(self, instance_id: UUID, command: str, timeout: int = 300) -> SSHResult:
        args = self._ssh_base_args(instance_id) + [command]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return SSHResult(
                exit_code=proc.returncode or 0,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
            )
        except asyncio.TimeoutError:
            proc.kill()
            return SSHResult(exit_code=-1, stdout="", stderr="Command timed out")
        except Exception as e:
            return SSHResult(exit_code=-1, stdout="", stderr=str(e))

    async def scp_to(self, instance_id: UUID, local_path: str, remote_path: str) -> SSHResult:
        cfg = self._configs[instance_id]
        key = self._key_files[instance_id]
        args = [
            "scp", "-r",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=15",
            "-i", key,
            "-P", str(cfg["port"]),
            local_path,
            f"{cfg['username']}@{cfg['host']}:{remote_path}",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            return SSHResult(
                exit_code=proc.returncode or 0,
                stdout=stdout.decode(errors="replace"),
                stderr=stderr.decode(errors="replace"),
            )
        except asyncio.TimeoutError:
            proc.kill()
            return SSHResult(exit_code=-1, stdout="", stderr="SCP timed out")
        except Exception as e:
            return SSHResult(exit_code=-1, stdout="", stderr=str(e))


ssh_pool = SSHConnectionPool()
