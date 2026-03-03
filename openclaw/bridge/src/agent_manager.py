"""
Agent workspace CRUD: create/delete/list agents, write AGENTS.md, TOOLS.md, SOUL.md, HEARTBEAT.md. M1.7.
"""
import json
import os
from pathlib import Path
from typing import Any

from src.config import settings

AGENTS_ROOT = Path(settings.AGENTS_ROOT)
AGENTS_ROOT.mkdir(parents=True, exist_ok=True)

DEFAULT_AGENTS_MD = """# Agents
{name}
"""
DEFAULT_TOOLS_MD = """# Tools
- read_file
- write_file
"""
DEFAULT_SOUL_MD = """# Soul
Role: {type}
"""
DEFAULT_HEARTBEAT_MD = """# Heartbeat
Interval: 60
"""


def _agent_dir(agent_id: str) -> Path:
    return AGENTS_ROOT / agent_id.replace("/", "_").replace("..", "")


def create_agent(agent_id: str, name: str, agent_type: str, config: dict[str, Any] | None = None) -> None:
    d = _agent_dir(agent_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "AGENTS.md").write_text(DEFAULT_AGENTS_MD.format(name=name), encoding="utf-8")
    (d / "TOOLS.md").write_text(DEFAULT_TOOLS_MD, encoding="utf-8")
    (d / "SOUL.md").write_text(DEFAULT_SOUL_MD.format(type=agent_type), encoding="utf-8")
    (d / "HEARTBEAT.md").write_text(DEFAULT_HEARTBEAT_MD, encoding="utf-8")
    if config:
        (d / "config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    (d / "status.json").write_text(json.dumps({"status": "CREATED", "pnl": 0}), encoding="utf-8")


def delete_agent(agent_id: str) -> None:
    d = _agent_dir(agent_id)
    if d.exists():
        for f in d.iterdir():
            f.unlink()
        d.rmdir()


def list_agents() -> list[dict]:
    out = []
    for p in AGENTS_ROOT.iterdir():
        if p.is_dir() and (p / "AGENTS.md").exists():
            status_file = p / "status.json"
            status = "UNKNOWN"
            pnl = 0
            if status_file.exists():
                try:
                    data = json.loads(status_file.read_text(encoding="utf-8"))
                    status = data.get("status", "UNKNOWN")
                    pnl = data.get("pnl", 0)
                except Exception:
                    pass
            out.append({"id": p.name, "name": p.name, "status": status, "pnl": pnl})
    return out


def get_agent(agent_id: str) -> dict | None:
    d = _agent_dir(agent_id)
    if not d.exists() or not (d / "AGENTS.md").exists():
        return None
    status_file = d / "status.json"
    status = "UNKNOWN"
    pnl = 0
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            status = data.get("status", "UNKNOWN")
            pnl = data.get("pnl", 0)
        except Exception:
            pass
    return {"id": d.name, "name": d.name, "status": status, "pnl": pnl}


def set_agent_status(agent_id: str, status: str, pnl: float | None = None) -> None:
    d = _agent_dir(agent_id)
    if not d.exists():
        return
    status_file = d / "status.json"
    data = {"status": status, "pnl": 0}
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    data["status"] = status
    if pnl is not None:
        data["pnl"] = pnl
    status_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
