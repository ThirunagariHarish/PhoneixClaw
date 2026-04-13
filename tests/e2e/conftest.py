"""
Playwright fixtures for Phoenix v2 E2E tests.
"""

import os

import pytest
from playwright.sync_api import Page


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Override browser context for E2E (viewport, etc.)."""
    return {**browser_context_args, "viewport": {"width": 1280, "height": 720}}


@pytest.fixture(scope="session")
def base_url():
    """Base URL for dashboard: staging/production or local dev.

    Set ``PHOENIX_E2E_BASE_URL`` (e.g. ``https://app.example.com``) for remote runs.
    """
    return os.environ.get("PHOENIX_E2E_BASE_URL", "http://localhost:3000")


@pytest.fixture
def dashboard_page(page: Page, base_url: str):
    """Navigate to dashboard root."""
    page.goto(base_url)
    return page


def _e2e_email() -> str:
    return os.environ.get("PHOENIX_E2E_EMAIL", "test@phoenix.io")


def _e2e_password() -> str:
    return os.environ.get("PHOENIX_E2E_PASSWORD", "testpassword123")


@pytest.fixture
def logged_in_page(page: Page, base_url: str):
    """Log in via /login; uses PHOENIX_E2E_EMAIL / PHOENIX_E2E_PASSWORD when set (staging/prod)."""
    page.goto(f"{base_url}/login")
    page.get_by_label("Email").fill(_e2e_email())
    page.get_by_label("Password").fill(_e2e_password())
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url("**/trades**", timeout=15000)
    return page
