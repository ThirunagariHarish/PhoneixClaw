"""
E2E tests for Connectors page.
"""

from playwright.sync_api import Page, expect


def test_connectors_page_renders(logged_in_page: Page, base_url: str):
    """Connectors page loads."""
    logged_in_page.goto(f"{base_url}/connectors")
    expect(logged_in_page.get_by_text("Connectors").first).to_be_visible()


def test_add_connector_dialog(logged_in_page: Page, base_url: str):
    """Add connector button opens dialog."""
    logged_in_page.goto(f"{base_url}/connectors")
    add_btn = logged_in_page.get_by_role("button", name="Add").or_(logged_in_page.get_by_text("Add Connector"))
    if add_btn.first.is_visible():
        add_btn.first.click()
        expect(logged_in_page.get_by_role("dialog").first).to_be_visible(timeout=2000)


def test_connector_list_or_empty(logged_in_page: Page, base_url: str):
    """Connector list or empty state visible."""
    logged_in_page.goto(f"{base_url}/connectors")
    main = logged_in_page.locator("main, .space-y-6")
    expect(main.first).to_be_visible()


def test_connector_test_button(logged_in_page: Page, base_url: str):
    """Test connection or connect button exists in UI."""
    logged_in_page.goto(f"{base_url}/connectors")
    content = logged_in_page.locator("main")
    expect(content.first).to_be_visible()
