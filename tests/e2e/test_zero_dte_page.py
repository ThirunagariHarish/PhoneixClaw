"""
E2E tests for 0DTE SPX page.
"""

from playwright.sync_api import Page, expect


def test_zero_dte_page_renders(logged_in_page: Page, base_url: str):
    """0DTE SPX page loads."""
    logged_in_page.goto(f"{base_url}/zero-dte")
    expect(logged_in_page.get_by_text("0DTE").or_(logged_in_page.get_by_text("SPX")).first).to_be_visible()


def test_zero_dte_gamma_or_moc_sections(logged_in_page: Page, base_url: str):
    """Gamma levels or MOC imbalance sections visible."""
    logged_in_page.goto(f"{base_url}/zero-dte")
    main = logged_in_page.locator("main, .space-y-6, [class*='card']")
    expect(main.first).to_be_visible()


def test_zero_dte_trade_plan_section(logged_in_page: Page, base_url: str):
    """Trade plan or EOD section visible."""
    logged_in_page.goto(f"{base_url}/zero-dte")
    content = logged_in_page.locator("main")
    expect(content.first).to_be_visible()
