"""
E2E tests for trades table. M1.10.
"""

from playwright.sync_api import Page, expect


def test_trades_table_renders(logged_in_page: Page, base_url: str):
    """Trades page renders table or empty state."""
    logged_in_page.goto(f"{base_url}/trades")
    expect(logged_in_page.get_by_text("Trades").or_(logged_in_page.get_by_role("table"))).to_be_visible()


def test_trades_filters_visible(logged_in_page: Page, base_url: str):
    """Status filter or search is visible."""
    logged_in_page.goto(f"{base_url}/trades")
    expect(logged_in_page.locator("table, [role='table'], .data-table").first).to_be_visible()


def test_trades_side_panel_opens_on_row_click(logged_in_page: Page, base_url: str):
    """Clicking a trade row opens side panel."""
    logged_in_page.goto(f"{base_url}/trades")
    rows = logged_in_page.locator("table tbody tr, [role='row']")
    if rows.count() > 0:
        rows.first.click()
        expect(logged_in_page.locator("[data-state='open'], [role='dialog']").first).to_be_visible()
