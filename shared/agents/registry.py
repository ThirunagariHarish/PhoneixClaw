import logging

from shared.agents.protocol import AgentPlugin

logger = logging.getLogger(__name__)

class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, AgentPlugin] = {}

    async def register(self, agent: AgentPlugin) -> None:
        self._agents[agent.name] = agent
        await agent.initialize()
        logger.info("Agent registered: %s v%s", agent.name, agent.version)

    async def unregister(self, name: str) -> None:
        agent = self._agents.pop(name, None)
        if agent:
            await agent.shutdown()
            logger.info("Agent unregistered: %s", name)

    def get(self, name: str) -> AgentPlugin | None:
        return self._agents.get(name)

    def list_agents(self) -> list[dict[str, str]]:
        return [{"name": a.name, "version": a.version, "description": a.description} for a in self._agents.values()]

    async def shutdown_all(self) -> None:
        for name in list(self._agents.keys()):
            await self.unregister(name)

agent_registry = AgentRegistry()
