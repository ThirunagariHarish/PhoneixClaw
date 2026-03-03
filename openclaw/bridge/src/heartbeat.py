"""
Collect heartbeat data from agent workspaces. M1.7.
"""
from src.agent_manager import list_agents


def collect_heartbeat() -> dict:
    agents = list_agents()
    return {"agents": agents, "count": len(agents)}
