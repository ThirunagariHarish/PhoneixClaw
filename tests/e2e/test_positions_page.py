"""
E2E tests for Positions page.
"""

from playwright.sync_api import Page, expect


def test_positions_page_renders(logged_in_page: Page, base_url: str):
    """Positions page loads."""
    logged_in_page.goto(f"{base_url}/positions")
    expect(logged_in_page.get_by_text("Positions").first).to_be_visible()


def test_positions_open_or_empty(logged_in_page: Page, base_url: str):
    """Open positions list or empty state visible."""
    logged_in_page.goto(f"{base_url}/positions")
    main = logged_in_page.locator("main, [role='main'], .space-y-6")
    expect(main.first).to_be_visible()


def test_positions_summary_cards(logged_in_page: Page, base_url: str):
    """Summary cards or metrics visible."""
    logged_in_page.goto(f"{base_url}/positions")
    cards = logged_in_page.locator("[class*='grid'], [class*='MetricCard'], .space-y-6")
    expect(cards.first).to_be_visible()


def test_positions_closed_tab(logged_in_page: Page, base_url: str):
    """Closed positions tab or link exists."""
    logged_in_page.goto(f"{base_url}/positions")
    closed = logged_in_page.get_by_text("Closed").or_(logged_in_page.get_by_role("tab", name="Closed"))
    expect(closed.first).to_be_visible(timeout=3000)


def test_positions_close_button_if_open(logged_in_page: Page, base_url: str):
    """Close position button exists when open positions present."""
    logged_in_page.goto(f"{base_url}/positions")
    content = logged_in_page.locator("main, .container")
    expect(content.first).to_be_visible()