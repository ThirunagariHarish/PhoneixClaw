"""Diagnostic endpoint that returns everything about the Claude Code SDK
runtime in production so we can debug hangs without SSHing in.

GET /api/v2/admin/claude-sdk-check  (admin-only)
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from fastapi import APIRouter, Request

from apps.api.src.deps import DbSession
from apps.api.src.routes.admin import _require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v2/admin", tags=["admin-diagnostics"])


async def _try_trivial_query(timeout_s: int = 20) -> dict:
    """Attempt a minimal Claude SDK query() call to confirm end-to-end health."""
    result: dict = {"status": "unknown"}
    start = time.time()
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except Exception as exc:
        return {"status": "import_failed", "error": str(exc)[:300]}

    opts = ClaudeAgentOptions(
        cwd="/tmp",
        permission_mode="dontAsk",
        allowed_tools=[],
    )

    async def _pump() -> int:
        count = 0
        async for _msg in query(prompt="Reply with the single word: ok", options=opts):
            count += 1
        return count

    try:
        msg_count = await asyncio.wait_for(_pump(), timeout=timeout_s)
        result = {
            "status": "ok",
            "messages_received": msg_count,
            "elapsed_s": round(time.time() - start, 2),
        }
    except asyncio.TimeoutError:
        result = {
            "status": "timeout",
            "timeout_s": timeout_s,
            "elapsed_s": round(time.time() - start, 2),
            "note": "query() hung without returning any messages",
        }
    except Exception as exc:
        result = {
            "status": "error",
            "error": str(exc)[:500],
            "elapsed_s": round(time.time() - start, 2),
        }
    return result


@router.get("/claude-sdk-check")
async def claude_sdk_check(request: Request, session: DbSession):
    """Admin diagnostic — returns a JSON snapshot of the Claude SDK runtime."""
    await _require_admin(request, session)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    home = os.environ.get("HOME", "/root")
    claude_dir = Path(home) / ".claude"

    report: dict = {
        "env": {
            "ANTHROPIC_API_KEY_present": bool(api_key),
            "ANTHROPIC_API_KEY_length": len(api_key),
            "HOME": home,
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "PATH": os.environ.get("PATH", "")[:500],
        },
        "claude_cli": {},
        "sdk_import": {},
        "claude_dir": {},
        "query_test": {},
    }

    # CLI
    claude_bin = shutil.which("claude")
    report["claude_cli"]["path"] = claude_bin
    if claude_bin:
        try:
            proc = subprocess.run(
                [claude_bin, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            report["claude_cli"]["version_stdout"] = proc.stdout.strip()
            report["claude_cli"]["version_stderr"] = proc.stderr.strip()[:200]
            report["claude_cli"]["returncode"] = proc.returncode
        except subprocess.TimeoutExpired:
            report["claude_cli"]["error"] = "--version hung >5s"
        except Exception as exc:
            report["claude_cli"]["error"] = str(exc)[:200]

    # SDK import
    try:
        import claude_agent_sdk  # noqa: F401
        report["sdk_import"]["ok"] = True
        report["sdk_import"]["module_path"] = getattr(claude_agent_sdk, "__file__", None)
    except Exception as exc:
        report["sdk_import"]["ok"] = False
        report["sdk_import"]["error"] = str(exc)[:300]

    # ~/.claude dir
    report["claude_dir"]["path"] = str(claude_dir)
    report["claude_dir"]["exists"] = claude_dir.exists()
    if claude_dir.exists():
        try:
            test_file = claude_dir / ".phoenix_diagnostic"
            test_file.write_text("ok")
            test_file.unlink()
            report["claude_dir"]["writable"] = True
        except Exception as exc:
            report["claude_dir"]["writable"] = False
            report["claude_dir"]["error"] = str(exc)[:200]

    # Trivial query (the real test)
    if report["sdk_import"].get("ok") and api_key and claude_bin:
        report["query_test"] = await _try_trivial_query(timeout_s=20)
    else:
        report["query_test"] = {"status": "skipped", "reason": "preconditions failed"}

    return report
