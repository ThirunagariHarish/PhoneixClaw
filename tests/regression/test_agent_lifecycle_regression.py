"""
Regression tests for agent lifecycle and state machine. M2.4.
"""

import uuid

import pytest

from services.orchestrator.src.state_machine import (
    TRANSITIONS,
    AgentState,
    AgentStateMachine,
    TransitionError,
)


@pytest.fixture
def agent_id():
    return str(uuid.uuid4())


@pytest.fixture
def valid_config():
    return {"strategy": "momentum", "symbols": ["SPY"], "risk_config": {"stop_loss_pct": 5}}


class TestAgentLifecycleRegression:
    """Agent creation, state transitions, pause/resume, deletion."""

    def test_agent_creation_valid_config(self, agent_id, valid_config):
        """Agent created with valid config starts in CREATED state."""
        sm = AgentStateMachine(agent_id, "CREATED")
        assert sm.state == AgentState.CREATED
        assert valid_config["strategy"] == "momentum"
        assert "risk_config" in valid_config

    def test_state_transition_created_to_backtesting(self, agent_id):
        """CREATED -> BACKTESTING is valid."""
        sm = AgentStateMachine(agent_id, "CREATED")
        sm.transition("BACKTESTING", reason="Backtest started")
        assert sm.state == AgentState.BACKTESTING

    def test_state_transition_backtesting_to_complete(self, agent_id):
        """BACKTESTING -> BACKTEST_COMPLETE is valid."""
        sm = AgentStateMachine(agent_id, "BACKTESTING")
        sm.transition("BACKTEST_COMPLETE", reason="Backtest finished")
        assert sm.state == AgentState.BACKTEST_COMPLETE

    def test_state_transition_complete_to_review(self, agent_id):
        """BACKTEST_COMPLETE -> REVIEW_PENDING is valid."""
        sm = AgentStateMachine(agent_id, "BACKTEST_COMPLETE")
        sm.transition("REVIEW_PENDING", reason="Awaiting approval")
        assert sm.state == AgentState.REVIEW_PENDING

    def test_state_transition_review_to_paper(self, agent_id):
        """REVIEW_PENDING -> PAPER is valid."""
        sm = AgentStateMachine(agent_id, "REVIEW_PENDING")
        sm.transition("PAPER", reason="Approved for paper")
        assert sm.state == AgentState.PAPER

    def test_state_transition_paper_to_live(self, agent_id):
        """PAPER -> LIVE is valid."""
        sm = AgentStateMachine(agent_id, "PAPER")
        sm.transition("LIVE", reason="Promoted to live")
        assert sm.state == AgentState.LIVE

    def test_invalid_state_transition_rejected(self, agent_id):
        """CREATED -> LIVE is invalid."""
        sm = AgentStateMachine(agent_id, "CREATED")
        with pytest.raises(TransitionError) as exc_info:
            sm.transition("LIVE", reason="Invalid")
        assert "LIVE" in str(exc_info.value) or "Cannot transition" in str(exc_info.value)

    def test_agent_pause_from_paper(self, agent_id):
        """PAPER -> PAUSED is valid."""
        sm = AgentStateMachine(agent_id, "PAPER")
        sm.transition("PAUSED", reason="User paused")
        assert sm.state == AgentState.PAUSED

    def test_agent_resume_from_paused(self, agent_id):
        """PAUSED -> PAPER is valid (resume)."""
        sm = AgentStateMachine(agent_id, "PAUSED")
        sm.transition("PAPER", reason="User resumed")
        assert sm.state == AgentState.PAPER

    def test_agent_deletion_cascade_stopped(self, agent_id):
        """STOPPED allows transition to CREATED (cascade/restart)."""
        sm = AgentStateMachine(agent_id, "LIVE")
        sm.transition("STOPPED", reason="Deleted")
        assert sm.state == AgentState.STOPPED
        assert AgentState.CREATED in TRANSITIONS.get(AgentState.STOPPED, set())

    def test_transition_history_recorded(self, agent_id):
        """State transitions are recorded in history."""
        sm = AgentStateMachine(agent_id, "CREATED")
        sm.transition("BACKTESTING", reason="Started")
        sm.transition("BACKTEST_COMPLETE", reason="Done")
        assert len(sm.history) == 2
        assert sm.history[0]["from"] == "CREATED"
        assert sm.history[0]["to"] == "BACKTESTING"
        assert sm.history[1]["to"] == "BACKTEST_COMPLETE"
