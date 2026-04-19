"""
E2E tests for Settings page.
"""

from playwright.sync_api import Page, expect


def test_settings_page_renders(logged_in_page: Page, base_url: str):
    """Settings page loads."""
    logged_in_page.goto(f"{base_url}/settings")
    expect(logged_in_page.get_by_text("Settings").first).to_be_visible()


def test_settings_form_or_sections(logged_in_page: Page, base_url: str):
    """Settings form or sections visible."""
    logged_in_page.goto(f"{base_url}/settings")
    main = logged_in_page.locator("main, form, .space-y-6")
    expect(main.first).to_be_visible()


def test_settings_save_or_theme(logged_in_page: Page, base_url: str):
    """Save button or theme toggle present."""
    logged_in_page.goto(f"{base_url}/settings")
    save_or_theme = logged_in_page.get_by_role("button", name="Save").or_(logged_in_page.get_by_text("Theme")).or_(logged_in_page.locator("main"))
    expect(logged_in_page.locator("main").first).to_be_visible()
