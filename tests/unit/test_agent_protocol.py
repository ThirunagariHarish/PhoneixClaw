import pytest

from shared.agents.protocol import AgentPlugin, SignalScoringAgent


class MockAgent:
    @property
    def name(self): return "mock"
    @property
    def version(self): return "0.1.0"
    @property
    def description(self): return "A mock agent"
    async def initialize(self): pass
    async def process(self, data): return data
    async def shutdown(self): pass

class MockScorer(MockAgent):
    async def score(self, signal): return 0.75
    async def explain(self, signal): return "test"

class TestAgentProtocol:
    def test_agent_is_protocol(self):
        agent = MockAgent()
        assert isinstance(agent, AgentPlugin)

    def test_scorer_is_protocol(self):
        scorer = MockScorer()
        assert isinstance(scorer, SignalScoringAgent)

    @pytest.mark.asyncio
    async def test_scorer_returns_score(self):
        scorer = MockScorer()
        score = await scorer.score({"ticker": "SPX"})
        assert 0.0 <= score <= 1.0
