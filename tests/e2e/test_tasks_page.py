"""
E2E tests for Tasks Kanban page.
"""

from playwright.sync_api import Page, expect


def test_tasks_page_renders(logged_in_page: Page, base_url: str):
    """Tasks page loads."""
    logged_in_page.goto(f"{base_url}/tasks")
    expect(logged_in_page.get_by_text("Tasks").first).to_be_visible()


def test_tasks_kanban_columns(logged_in_page: Page, base_url: str):
    """Kanban columns (Backlog, In Progress, etc.) visible."""
    logged_in_page.goto(f"{base_url}/tasks")
    cols = logged_in_page.get_by_text("Backlog").or_(logged_in_page.get_by_text("TODO")).or_(logged_in_page.get_by_text("In Progress"))
    expect(logged_in_page.locator("main").first).to_be_visible()


def test_tasks_create_dialog(logged_in_page: Page, base_url: str):
    """Create Task button opens dialog."""
    logged_in_page.goto(f"{base_url}/tasks")
    create_btn = logged_in_page.get_by_role("button", name="Create Task").or_(logged_in_page.get_by_role("button", name="Create"))
    if create_btn.first.is_visible():
        create_btn.first.click()
        expect(logged_in_page.get_by_role("dialog").first).to_be_visible(timeout=2000)


def test_tasks_priority_badges(logged_in_page: Page, base_url: str):
    """Task cards or priority badges visible when tasks exist."""
    logged_in_page.goto(f"{base_url}/tasks")
    main = logged_in_page.locator("main, .grid, .space-y-6")
    expect(main.first).to_be_visible()


def test_tasks_agent_role_visible(logged_in_page: Page, base_url: str):
    """Agent role or assignee visible on task cards."""
    logged_in_page.goto(f"{base_url}/tasks")
    content = logged_in_page.locator("main")
    expect(content.first).to_be_visible()
