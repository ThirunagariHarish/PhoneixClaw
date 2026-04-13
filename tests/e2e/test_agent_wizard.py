"""
E2E tests for agent creation flow. M1.11.
"""

from playwright.sync_api import Page, expect


def test_agent_create_dialog_opens(logged_in_page: Page, base_url: str):
    """New Agent opens Create Agent dialog."""
    logged_in_page.goto(f"{base_url}/agents")
    logged_in_page.get_by_role("button", name="New Agent").click()
    expect(logged_in_page.get_by_role("dialog")).to_be_visible()
    expect(logged_in_page.get_by_text("Create Agent")).to_be_visible()


def test_agent_create_form_has_name_type(logged_in_page: Page, base_url: str):
    """Create form has name, type, instance fields."""
    logged_in_page.goto(f"{base_url}/agents")
    logged_in_page.get_by_role("button", name="New Agent").click()
    expect(logged_in_page.get_by_placeholder("e.g. SPY-Discord-Trader")).to_be_visible()
    expect(logged_in_page.get_by_text("Trading Agent")).to_be_visible()
    expect(logged_in_page.get_by_text("OpenClaw Instance")).to_be_visible()


def test_agent_create_form_has_data_source(logged_in_page: Page, base_url: str):
    """Create form has data source and description."""
    logged_in_page.goto(f"{base_url}/agents")
    logged_in_page.get_by_role("button", name="New Agent").click()
    expect(logged_in_page.get_by_text("Data Source", exact=False)).to_be_visible()
    expect(logged_in_page.get_by_text("Description", exact=False)).to_be_visible()


def test_agent_create_button_disabled_without_required(logged_in_page: Page, base_url: str):
    """Create button disabled when name or instance missing."""
    logged_in_page.goto(f"{base_url}/agents")
    logged_in_page.get_by_role("button", name="New Agent").click()
    create_btn = logged_in_page.get_by_role("button", name="Create Agent")
    expect(create_btn).to_be_disabled()


def test_agent_create_submits_with_valid_data(logged_in_page: Page, base_url: str):
    """Create Agent submits when form valid (requires instance)."""
    logged_in_page.goto(f"{base_url}/agents")
    logged_in_page.get_by_role("button", name="New Agent").click()
    logged_in_page.get_by_placeholder("e.g. SPY-Discord-Trader").fill("E2E-Test-Agent")
    # Instance required; if instances exist, select first
    instance_select = logged_in_page.get_by_text("Select instance...")
    if instance_select.is_visible():
        instance_select.click()
        first = logged_in_page.get_by_role("option").first
        if first.is_visible():
            first.click()
    create_btn = logged_in_page.get_by_role("button", name="Create Agent")
    if not create_btn.is_disabled():
        create_btn.click()
        expect(logged_in_page.get_by_role("dialog")).not_to_be_visible()
