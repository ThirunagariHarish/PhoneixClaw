
import pytest
from services.source_orchestrator.src.orchestrator import SourceOrchestrator


class TestSourceOrchestrator:
    def test_starts_empty(self):
        orch = SourceOrchestrator()
        assert len(orch._active_workers) == 0

    @pytest.mark.asyncio
    async def test_stop_clears_workers(self):
        orch = SourceOrchestrator()
        orch._active_workers = {"src-1": {"status": "running"}}
        await orch.stop()
        assert len(orch._active_workers) == 0
        assert orch._running is False
