"""Tests for agents/analyst/personas/library.py"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
from agents.analyst.personas.library import PERSONA_LIBRARY, get_persona

EXPECTED_PERSONAS = [
    "aggressive_momentum", "conservative_swing", "options_flow_specialist",
    "dark_pool_hunter", "sentiment_trader", "scalper"
]


def test_all_personas_loadable():
    for pid in EXPECTED_PERSONAS:
        p = PERSONA_LIBRARY[pid]
        assert p.id == pid
        assert p.name
        assert p.emoji


def test_tool_weights_sum_to_approximately_one():
    for pid, persona in PERSONA_LIBRARY.items():
        total = sum(persona.tool_weights.values())
        assert abs(total - 1.0) < 0.01, f"Persona {pid} tool_weights sum to {total}"


def test_get_persona_returns_correct_persona():
    p = get_persona("aggressive_momentum")
    assert p.id == "aggressive_momentum"


def test_get_persona_raises_on_unknown():
    with pytest.raises((KeyError, ValueError)):
        get_persona("nonexistent_persona")


def test_confidence_threshold_in_valid_range():
    for persona in PERSONA_LIBRARY.values():
        assert 0 <= persona.min_confidence_threshold <= 100


def test_stop_loss_pct_values():
    from agents.analyst.personas.base import PersonaConfig
    for persona in PERSONA_LIBRARY.values():
        pct = persona.stop_loss_pct()
        assert pct > 0


def test_balanced_persona_exists_with_equal_weights():
    """balanced persona must exist (used by scorer tests) with equal 0.25 weights."""
    p = PERSONA_LIBRARY["balanced"]
    assert p.id == "balanced"
    for key in ("chart", "options_flow", "dark_pool", "sentiment"):
        assert abs(p.tool_weights[key] - 0.25) < 0.001, (
            f"balanced.tool_weights[{key}] = {p.tool_weights[key]}, expected 0.25"
        )


def test_dark_pool_hunter_weights_sum_to_one():
    """Phase 1 redistributed dark_pool_hunter weights must still sum to 1.0."""
    p = PERSONA_LIBRARY["dark_pool_hunter"]
    total = sum(p.tool_weights.values())
    assert abs(total - 1.0) < 0.01, f"dark_pool_hunter weights sum to {total}"
