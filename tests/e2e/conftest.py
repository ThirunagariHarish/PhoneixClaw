"""
Playwright fixtures for Phoenix v2 E2E tests.
"""

import pytest
from playwright.sync_api import Page


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Override browser context for E2E (viewport, etc.)."""
    return {**browser_context_args, "viewport": {"width": 1280, "height": 720}}


@pytest.fixture(scope="session")
def base_url():
    """Base URL for dashboard (default local dev)."""
    return "http://localhost:3000"


@pytest.fixture
def dashboard_page(page: Page, base_url: str):
    """Navigate to dashboard root."""
    page.goto(base_url)
    return page
