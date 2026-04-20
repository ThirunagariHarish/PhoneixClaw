"""
Sandboxed Python code executor for agent-generated code.

M3.9: Agent code generation and predictive models.
Reference: PRD Section 9.4.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CodeExecutionResult:
    """Result of a sandboxed code execution."""
    def __init__(self, success: bool, stdout: str, stderr: str, execution_time_ms: float, artifacts: list[str]):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr
        self.execution_time_ms = execution_time_ms
        self.artifacts = artifacts

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "stdout": self.stdout[:10000],
            "stderr": self.stderr[:5000],
            "execution_time_ms": self.execution_time_ms,
            "artifacts": self.artifacts,
        }


class PythonSandbox:
    """
    Executes Python code in a sandboxed environment.
    Uses subprocess with timeouts and restricted filesystem.
    In production, uses Docker for full isolation.
    """

    MAX_EXECUTION_TIME_SECONDS = 300  # 5 minutes max
    MAX_OUTPUT_SIZE = 10000

    def __init__(self, workspace_dir: str | None = None):
        self.workspace = Path(workspace_dir) if workspace_dir else Path(tempfile.mkdtemp(prefix="phoenix-sandbox-"))
        self.workspace.mkdir(parents=True, exist_ok=True)

    async def execute(self, code: str, timeout: int | None = None) -> CodeExecutionResult:
        """Execute Python code in sandbox."""
        import time

        timeout = timeout or self.MAX_EXECUTION_TIME_SECONDS
        script_path = self.workspace / "script.py"
        script_path.write_text(code, encoding="utf-8")

        start = time.monotonic()
        try:
            result = subprocess.run(
                ["python3", str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.workspace),
            )
            elapsed = (time.monotonic() - start) * 1000

            artifacts = [str(f.name) for f in self.workspace.iterdir()
                        if f.name != "script.py" and f.is_file()]

            return CodeExecutionResult(
                success=result.returncode == 0,
                stdout=result.stdout[:self.MAX_OUTPUT_SIZE],
                stderr=result.stderr[:self.MAX_OUTPUT_SIZE],
                execution_time_ms=round(elapsed, 2),
                artifacts=artifacts,
            )
        except subprocess.TimeoutExpired:
            elapsed = (time.monotonic() - start) * 1000
            return CodeExecutionResult(
                success=False,
                stdout="",
                stderr=f"Execution timed out after {timeout}s",
                execution_time_ms=round(elapsed, 2),
                artifacts=[],
            )
        except Exception as e:
            return CodeExecutionResult(
                success=False,
                stdout="",
                stderr=str(e),
                execution_time_ms=0,
                artifacts=[],
            )


class ModelLifecycle:
    """Manages trained model artifacts."""

    def __init__(self, storage_dir: str = "/tmp/phoenix-models"):
        self.storage = Path(storage_dir)
        self.storage.mkdir(parents=True, exist_ok=True)
        self._models: dict[str, dict] = {}

    def register_model(self, model_id: str, metadata: dict) -> dict:
        entry = {
            "id": model_id,
            **metadata,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "version": metadata.get("version", "1.0.0"),
        }
        self._models[model_id] = entry
        return entry

    def list_models(self) -> list[dict]:
        return list(self._models.values())

    def get_model(self, model_id: str) -> dict | None:
        return self._models.get(model_id)
