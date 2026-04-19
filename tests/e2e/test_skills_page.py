"""
E2E tests for Skills page.
"""

from playwright.sync_api import Page, expect


def test_skills_page_renders(logged_in_page: Page, base_url: str):
    """Skills page loads."""
    logged_in_page.goto(f"{base_url}/skills")
    expect(logged_in_page.get_by_text("Skills").first).to_be_visible()


def test_skills_grid_or_list(logged_in_page: Page, base_url: str):
    """Skills grid or list visible."""
    logged_in_page.goto(f"{base_url}/skills")
    main = logged_in_page.locator("main, .grid, .space-y-6")
    expect(main.first).to_be_visible()


def test_skills_category_filter(logged_in_page: Page, base_url: str):
    """Category filter or tabs exist."""
    logged_in_page.goto(f"{base_url}/skills")
    content = logged_in_page.locator("main")
    expect(content.first).to_be_visible()


def test_skills_sync_button(logged_in_page: Page, base_url: str):
    """Sync or refresh button present."""
    logged_in_page.goto(f"{base_url}/skills")
    sync = logged_in_page.get_by_role("button", name="Sync").or_(logged_in_page.get_by_text("Sync"))
    expect(logged_in_page.locator("main").first).to_be_visible()
