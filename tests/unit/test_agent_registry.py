import pytest

from shared.agents.registry import AgentRegistry


class FakeAgent:
    @property
    def name(self): return "fake"
    @property
    def version(self): return "1.0"
    @property
    def description(self): return "Fake"
    async def initialize(self): pass
    async def process(self, data): return data
    async def shutdown(self): pass

class TestAgentRegistry:
    @pytest.mark.asyncio
    async def test_register_and_get(self):
        reg = AgentRegistry()
        agent = FakeAgent()
        await reg.register(agent)
        assert reg.get("fake") is agent

    @pytest.mark.asyncio
    async def test_unregister(self):
        reg = AgentRegistry()
        await reg.register(FakeAgent())
        await reg.unregister("fake")
        assert reg.get("fake") is None

    @pytest.mark.asyncio
    async def test_list_agents(self):
        reg = AgentRegistry()
        await reg.register(FakeAgent())
        agents = reg.list_agents()
        assert len(agents) == 1
        assert agents[0]["name"] == "fake"

    @pytest.mark.asyncio
    async def test_shutdown_all(self):
        reg = AgentRegistry()
        await reg.register(FakeAgent())
        await reg.shutdown_all()
        assert len(reg.list_agents()) == 0
