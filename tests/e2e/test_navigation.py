"""
E2E tests for dashboard navigation.
"""

from playwright.sync_api import Page, expect


def test_sidebar_renders_nav_items(logged_in_page: Page, base_url: str):
    """Sidebar shows main nav links."""
    logged_in_page.goto(f"{base_url}/trades")
    expect(logged_in_page.get_by_text("Trades").first).to_be_visible()
    expect(logged_in_page.get_by_text("Positions").first).to_be_visible()
    expect(logged_in_page.get_by_text("Agents").first).to_be_visible()


def test_click_trades_navigates(logged_in_page: Page, base_url: str):
    """Clicking Trades navigates to trades page."""
    logged_in_page.goto(f"{base_url}/agents")
    logged_in_page.get_by_role("link", name="Trades").first.click()
    expect(logged_in_page).to_have_url("**/trades**")


def test_click_positions_navigates(logged_in_page: Page, base_url: str):
    """Clicking Positions navigates to positions page."""
    logged_in_page.goto(f"{base_url}/trades")
    logged_in_page.get_by_role("link", name="Positions").first.click()
    expect(logged_in_page).to_have_url("**/positions**")


def test_click_agents_navigates(logged_in_page: Page, base_url: str):
    """Clicking Agents navigates to agents page."""
    logged_in_page.goto(f"{base_url}/trades")
    logged_in_page.get_by_role("link", name="Agents").first.click()
    expect(logged_in_page).to_have_url("**/agents**")


def test_mobile_more_menu(page: Page, base_url: str):
    """On mobile viewport, More or menu is present."""
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto(base_url)
    nav = page.locator("nav a, [role='link'], button")
    expect(nav.first).to_be_visible()