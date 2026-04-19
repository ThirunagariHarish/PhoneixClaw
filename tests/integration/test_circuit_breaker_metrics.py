"""Integration tests for circuit breaker metrics emission."""

import asyncio

import pytest
from prometheus_client import REGISTRY, generate_latest

from shared.observability.metrics import circuit_breaker_gauge
from shared.utils.circuit_breaker import CircuitBreaker


@pytest.mark.asyncio
async def test_circuit_breaker_closed_to_open():
    """Circuit breaker emits gauge update on transition to OPEN."""
    breaker = CircuitBreaker("test_breaker", failure_threshold=2, cooldown_seconds=1)

    # Start closed
    assert breaker.state == "closed"

    # Fail twice to trip breaker
    try:
        async with breaker:
            raise ValueError("Simulated failure 1")
    except ValueError:
        pass

    try:
        async with breaker:
            raise ValueError("Simulated failure 2")
    except ValueError:
        pass

    # Breaker should now be open
    assert breaker.state == "open"

    # Check metric
    output = generate_latest(REGISTRY).decode("utf-8")
    assert "phoenix_circuit_breaker_state_by_name" in output
    assert 'name="test_breaker"' in output
    # Value should be 2 (OPEN)
    assert 'phoenix_circuit_breaker_state_by_name{name="test_breaker"} 2.0' in output


@pytest.mark.asyncio
async def test_circuit_breaker_open_to_closed():
    """Circuit breaker emits gauge update on recovery to CLOSED."""
    breaker = CircuitBreaker("test_recovery", failure_threshold=1, cooldown_seconds=0.1)

    # Trip breaker
    try:
        async with breaker:
            raise ValueError("Failure")
    except ValueError:
        pass

    assert breaker.state == "open"

    # Wait for cooldown
    await asyncio.sleep(0.2)

    # State should be half_open
    assert breaker.state == "half_open"

    # Successful probe should close breaker
    async with breaker:
        pass  # Success

    assert breaker.state == "closed"

    # Check metric
    output = generate_latest(REGISTRY).decode("utf-8")
    # Value should be 0 (CLOSED)
    lines = [line for line in output.split("\n") if "phoenix_circuit_breaker_state_by_name" in line and "test_recovery" in line and not line.startswith("#")]
    assert any("0.0" in line for line in lines)


@pytest.mark.asyncio
async def test_multiple_breakers_independent_metrics():
    """Multiple circuit breakers emit independent gauge values."""
    breaker_a = CircuitBreaker("breaker_a", failure_threshold=1, cooldown_seconds=1)
    breaker_b = CircuitBreaker("breaker_b", failure_threshold=1, cooldown_seconds=1)

    # Trip breaker_a
    try:
        async with breaker_a:
            raise ValueError("Fail A")
    except ValueError:
        pass

    # breaker_a is open, breaker_b is closed
    assert breaker_a.state == "open"
    assert breaker_b.state == "closed"

    output = generate_latest(REGISTRY).decode("utf-8")
    assert 'name="breaker_a"' in output
    assert 'name="breaker_b"' in output
