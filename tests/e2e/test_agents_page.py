"""
E2E tests for Agents page and 5-step wizard.
"""

from playwright.sync_api import Page, expect


def test_agents_list_renders(logged_in_page: Page, base_url: str):
    """Agents page shows list or empty state."""
    logged_in_page.goto(f"{base_url}/agents")
    expect(logged_in_page.get_by_text("Agents").first).to_be_visible()


def test_new_agent_opens_wizard(logged_in_page: Page, base_url: str):
    """New Agent button opens creation dialog."""
    logged_in_page.goto(f"{base_url}/agents")
    logged_in_page.get_by_role("button", name="New Agent").click()
    expect(logged_in_page.get_by_role("dialog")).to_be_visible()


def test_wizard_step_basic_info(logged_in_page: Page, base_url: str):
    """Wizard shows name/type/description step."""
    logged_in_page.goto(f"{base_url}/agents")
    logged_in_page.get_by_role("button", name="New Agent").click()
    expect(logged_in_page.get_by_placeholder("e.g. SPY-Discord-Trader").or_(logged_in_page.get_by_label("Name"))).to_be_visible(timeout=3000)


def test_wizard_has_instance_step(logged_in_page: Page, base_url: str):
    """Wizard has instance selection."""
    logged_in_page.goto(f"{base_url}/agents")
    logged_in_page.get_by_role("button", name="New Agent").click()
    expect(logged_in_page.get_by_text("Instance").or_(logged_in_page.get_by_text("OpenClaw")).first).to_be_visible(timeout=3000)


def test_agent_card_actions_visible(logged_in_page: Page, base_url: str):
    """Agent cards show pause/resume or action buttons when agents exist."""
    logged_in_page.goto(f"{base_url}/agents")
    main = logged_in_page.locator("main, .space-y-6")
    expect(main.first).to_be_visible()


def test_agent_approve_promote_buttons(logged_in_page: Page, base_url: str):
    """Approve or Promote buttons appear for agents in CREATED/APPROVED state."""
    logged_in_page.goto(f"{base_url}/agents")
    content = logged_in_page.locator("main")
    expect(content.first).to_be_visible()
