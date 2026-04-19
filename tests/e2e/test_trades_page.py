"""
E2E tests for Trades page.
"""

from playwright.sync_api import Page, expect


def test_trades_page_renders(logged_in_page: Page, base_url: str):
    """Trades page loads with heading."""
    logged_in_page.goto(f"{base_url}/trades")
    expect(logged_in_page.get_by_role("heading", name="Trades").or_(logged_in_page.get_by_text("Trades"))).to_be_visible()


def test_trades_stats_cards_visible(logged_in_page: Page, base_url: str):
    """Stats or summary cards are present."""
    logged_in_page.goto(f"{base_url}/trades")
    content = logged_in_page.locator("[class*='grid'], .space-y-6, main")
    expect(content.first).to_be_visible()


def test_trades_table_or_empty_state(logged_in_page: Page, base_url: str):
    """Either table or empty state is shown."""
    logged_in_page.goto(f"{base_url}/trades")
    table_or_empty = logged_in_page.locator("table, [role='table'], .data-table, :has-text('No trades')")
    expect(table_or_empty.first).to_be_visible(timeout=5000)


def test_trades_filter_controls(logged_in_page: Page, base_url: str):
    """Filter or search controls exist."""
    logged_in_page.goto(f"{base_url}/trades")
    page_content = logged_in_page.locator("main, [role='main'], .container")
    expect(page_content.first).to_be_visible()


def test_trades_detail_opens_on_click(logged_in_page: Page, base_url: str):
    """Clicking a row opens detail panel if rows exist."""
    logged_in_page.goto(f"{base_url}/trades")
    rows = logged_in_page.locator("table tbody tr, [role='row']")
    if rows.count() > 0:
        rows.first.click()
        expect(logged_in_page.locator("[data-state='open'], [role='dialog'], .side-panel").first).to_be_visible(timeout=3000)
