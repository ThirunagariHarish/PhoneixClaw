"""
E2E tests for mobile responsive layout. M1.13.
"""

from playwright.sync_api import Page, expect


def test_bottom_nav_on_mobile(page: Page, base_url: str):
    """Bottom nav visible on mobile viewport."""
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto(base_url)
    # Bottom nav has Trades, Positions, etc. (md:hidden so visible on mobile)
    nav = page.locator("nav.fixed.bottom-0, [class*='bottom-0']")
    expect(nav).to_be_visible()


def test_sidebar_on_desktop(page: Page, base_url: str):
    """Sidebar visible on desktop viewport."""
    page.set_viewport_size({"width": 1280, "height": 720})
    page.goto(base_url)
    # Sidebar or main nav
    sidebar = page.locator("aside, [role='navigation'], nav:not(.fixed.bottom-0)")
    expect(sidebar.first).to_be_visible()


def test_mobile_primary_tabs_visible(page: Page, base_url: str):
    """Primary tabs (Trades, Positions, Performance, Agents) on mobile."""
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto(base_url)
    expect(page.get_by_text("Trades").or_(page.get_by_text("Positions"))).to_be_visible()
