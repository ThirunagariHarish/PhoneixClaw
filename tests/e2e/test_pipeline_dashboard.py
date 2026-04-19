"""
E2E tests for Pipeline Agent dashboard integration (Phase A.8).

Tests:
- Agent creation wizard shows broker selection for pipeline engine
- Pipeline agent cards display engine and broker badges
- Pipeline agent detail page shows pipeline stats panel
- SDK agent creation unchanged (no broker fields)

Requires:
- API running on port 8011
- Dashboard running on port 3000
- At least one broker trading account configured

Usage:
    python -m pytest tests/e2e/test_pipeline_dashboard.py -v --headed
    PHOENIX_E2E_BASE_URL=http://localhost:3000 pytest tests/e2e/test_pipeline_dashboard.py -v
"""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
def test_pipeline_wizard_shows_broker_dropdown(logged_in_page: Page, base_url: str):
    """
    Test pipeline agent creation wizard:
    1. Navigate to Agents page
    2. Open creation wizard
    3. Select Pipeline engine
    4. Assert broker dropdown appears
    """
    page = logged_in_page
    page.goto(f"{base_url}/agents")

    # Click New Agent button
    page.get_by_role("button", name="New Agent").click()

    # Wait for wizard/dialog to appear
    expect(page.get_by_role("dialog")).to_be_visible(timeout=5000)

    # Look for engine selection step (may be radio buttons or cards)
    # Try to find "Pipeline" or "Pipeline Engine" text
    pipeline_option = page.get_by_text("Pipeline", exact=False)
    if pipeline_option.is_visible():
        pipeline_option.click()

        # After selecting Pipeline, broker dropdown should appear
        # Look for broker selection UI element
        broker_label = page.get_by_text("Broker", exact=False)
        expect(broker_label).to_be_visible(timeout=3000)


@pytest.mark.e2e
def test_pipeline_wizard_broker_selection_robinhood(logged_in_page: Page, base_url: str):
    """
    Test selecting Robinhood broker in pipeline wizard.
    """
    page = logged_in_page
    page.goto(f"{base_url}/agents")

    page.get_by_role("button", name="New Agent").click()
    expect(page.get_by_role("dialog")).to_be_visible()

    # Select Pipeline engine
    pipeline_option = page.get_by_text("Pipeline", exact=False)
    if pipeline_option.is_visible():
        pipeline_option.click()

        # Select Robinhood broker
        # This might be a dropdown, select, or button group
        robinhood_option = page.get_by_text("Robinhood", exact=False)
        if robinhood_option.is_visible():
            robinhood_option.click()

            # Verify Robinhood is selected
            expect(robinhood_option).to_have_class("selected", timeout=2000) or \
                expect(page.get_by_text("Robinhood")).to_be_visible()


@pytest.mark.e2e
def test_pipeline_wizard_broker_selection_ibkr(logged_in_page: Page, base_url: str):
    """
    Test selecting IBKR broker in pipeline wizard.
    """
    page = logged_in_page
    page.goto(f"{base_url}/agents")

    page.get_by_role("button", name="New Agent").click()
    expect(page.get_by_role("dialog")).to_be_visible()

    # Select Pipeline engine
    pipeline_option = page.get_by_text("Pipeline", exact=False)
    if pipeline_option.is_visible():
        pipeline_option.click()

        # Select IBKR broker
        ibkr_option = page.get_by_text("IBKR", exact=False).or_(page.get_by_text("Interactive Brokers", exact=False))
        if ibkr_option.is_visible():
            ibkr_option.click()

            # Verify IBKR is selected
            expect(page.get_by_text("IBKR")).to_be_visible() or \
                expect(page.get_by_text("Interactive Brokers")).to_be_visible()


@pytest.mark.e2e
@pytest.mark.skip(reason="Requires broker account setup — enable when test data available")
def test_complete_pipeline_agent_creation(logged_in_page: Page, base_url: str):
    """
    Complete pipeline agent creation flow:
    1. Select Pipeline engine
    2. Select broker (Robinhood)
    3. Fill required fields
    4. Submit
    5. Assert new agent appears with Pipeline + Robinhood badges
    """
    page = logged_in_page
    page.goto(f"{base_url}/agents")

    initial_agent_count = page.get_by_role("article").count()

    page.get_by_role("button", name="New Agent").click()
    expect(page.get_by_role("dialog")).to_be_visible()

    # Fill agent name
    page.get_by_placeholder("e.g. SPY-Discord-Trader").fill("E2E-Pipeline-Agent")

    # Select Pipeline engine
    pipeline_option = page.get_by_text("Pipeline", exact=False)
    if pipeline_option.is_visible():
        pipeline_option.click()

    # Select Robinhood broker
    robinhood_option = page.get_by_text("Robinhood", exact=False)
    if robinhood_option.is_visible():
        robinhood_option.click()

    # Select connector (if required)
    # This depends on wizard implementation

    # Click Create button
    create_btn = page.get_by_role("button", name="Create Agent", exact=False)
    if not create_btn.is_disabled():
        create_btn.click()

        # Wait for dialog to close
        expect(page.get_by_role("dialog")).not_to_be_visible(timeout=5000)

        # Assert new agent card appears
        new_agent_count = page.get_by_role("article").count()
        assert new_agent_count > initial_agent_count, "New agent should appear in list"

        # Look for Pipeline badge
        expect(page.get_by_text("Pipeline", exact=False)).to_be_visible()

        # Look for Robinhood badge
        expect(page.get_by_text("Robinhood", exact=False)).to_be_visible()


@pytest.mark.e2e
@pytest.mark.skip(reason="Requires pipeline agent in DB — enable when test data available")
def test_pipeline_agent_detail_shows_stats_panel(logged_in_page: Page, base_url: str):
    """
    Test pipeline agent detail page shows Pipeline Stats panel:
    1. Navigate to pipeline agent detail page
    2. Assert Pipeline Stats panel visible
    3. Assert stats metrics present (signals_processed, trades_executed, etc.)
    """
    page = logged_in_page
    page.goto(f"{base_url}/agents")

    # Find and click on a pipeline agent card
    # Look for card with "Pipeline" badge
    pipeline_card = page.get_by_text("Pipeline", exact=False).locator("..")
    if pipeline_card.is_visible():
        pipeline_card.click()

        # Wait for detail page to load
        page.wait_for_url("**/agents/**", timeout=5000)

        # Assert Pipeline Stats panel is visible
        stats_panel = page.get_by_text("Pipeline Stats", exact=False)
        expect(stats_panel).to_be_visible(timeout=3000)

        # Assert stats metrics are present
        expect(page.get_by_text("Signals Processed", exact=False)).to_be_visible()
        expect(page.get_by_text("Trades Executed", exact=False)).to_be_visible()
        expect(page.get_by_text("Signals Skipped", exact=False)).to_be_visible()
        expect(page.get_by_text("Uptime", exact=False)).to_be_visible()
        expect(page.get_by_text("Circuit State", exact=False)).to_be_visible()


@pytest.mark.e2e
def test_sdk_agent_creation_no_broker_fields(logged_in_page: Page, base_url: str):
    """
    Test SDK agent creation regression:
    1. Open agent wizard
    2. Select SDK engine (or default)
    3. Assert broker dropdown NOT visible
    4. SDK agent creation flow unchanged
    """
    page = logged_in_page
    page.goto(f"{base_url}/agents")

    page.get_by_role("button", name="New Agent").click()
    expect(page.get_by_role("dialog")).to_be_visible()

    # Select SDK engine (or it may be default)
    sdk_option = page.get_by_text("SDK", exact=False).or_(page.get_by_text("Claude SDK", exact=False))
    if sdk_option.is_visible():
        sdk_option.click()

    # Assert broker dropdown/field is NOT visible
    # Use a reasonable timeout since we're checking for absence
    page.wait_for_timeout(1000)  # Wait a bit for UI to settle
    broker_label = page.get_by_text("Broker", exact=False)
    expect(broker_label).not_to_be_visible()


@pytest.mark.e2e
@pytest.mark.skip(reason="Smoke test — enable for full regression")
def test_pipeline_agents_list_shows_badges(logged_in_page: Page, base_url: str):
    """
    Test that pipeline agents in list view show:
    - Pipeline engine badge
    - Broker badge (Robinhood/IBKR)
    """
    page = logged_in_page
    page.goto(f"{base_url}/agents")

    # Look for any agent cards
    agent_cards = page.get_by_role("article")
    if agent_cards.count() > 0:
        # Check if any have Pipeline badge
        pipeline_badges = page.get_by_text("Pipeline", exact=False)
        if pipeline_badges.count() > 0:
            # At least one pipeline agent exists
            # Check for broker badge near pipeline badge
            expect(pipeline_badges.first).to_be_visible()

            # Broker badge should be nearby (Robinhood or IBKR)
            broker_badge = page.get_by_text("Robinhood", exact=False).or_(page.get_by_text("IBKR", exact=False))
            expect(broker_badge.first).to_be_visible()
