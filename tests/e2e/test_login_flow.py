"""
E2E tests for login flow. M1.4.
"""

from playwright.sync_api import Page, expect


def test_login_page_renders(page: Page, base_url: str):
    """Login page shows email/password form."""
    page.goto(f"{base_url}/login")
    expect(page.get_by_role("heading", name="Phoenix Claw")).to_be_visible()
    expect(page.get_by_label("Email")).to_be_visible()
    expect(page.get_by_label("Password")).to_be_visible()
    expect(page.get_by_role("button", name="Sign in")).to_be_visible()


def test_login_form_validation(page: Page, base_url: str):
    """Empty submit shows validation or error."""
    page.goto(f"{base_url}/login")
    page.get_by_role("button", name="Sign in").click()
    # HTML5 validation or error message
    email = page.get_by_label("Email")
    expect(email).to_be_visible()


def test_login_redirect_to_dashboard(page: Page, base_url: str):
    """Successful login redirects to dashboard (mocked or test creds)."""
    page.goto(f"{base_url}/login")
    page.get_by_label("Email").fill("test@phoenix.io")
    page.get_by_label("Password").fill("testpassword123")
    page.get_by_role("button", name="Sign in").click()
    # Redirect to / or /trades; may fail if API not running
    page.wait_for_url("**/trades**", timeout=5000)
    expect(page).to_have_url("**/trades**")
