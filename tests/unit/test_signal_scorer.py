import pytest

from services.signal_scorer.src.scorer import SimpleSignalScorer


@pytest.fixture
def scorer():
    return SimpleSignalScorer()

class TestSimpleSignalScorer:
    @pytest.mark.asyncio
    async def test_score_major_index(self, scorer):
        score = await scorer.score({"ticker": "SPX", "expiration": "2026-02-20", "price": 4.80})
        assert score > 0.5

    @pytest.mark.asyncio
    async def test_score_unknown_ticker(self, scorer):
        score = await scorer.score({"ticker": "RANDOMXYZ", "price": 4.80})
        assert score >= 0.0

    @pytest.mark.asyncio
    async def test_score_bounded(self, scorer):
        score = await scorer.score({"ticker": "SPX", "expiration": "2026-02-20", "price": 5.0, "quantity": 2})
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_explain(self, scorer):
        explanation = await scorer.explain({"ticker": "SPX", "expiration": "2026-02-20"})
        assert "SPX" in explanation

    @pytest.mark.asyncio
    async def test_process_adds_score(self, scorer):
        result = await scorer.process({"ticker": "SPX", "price": 4.80})
        assert "signal_score" in result
        assert "scored_by" in result
