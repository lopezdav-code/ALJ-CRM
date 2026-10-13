"""Office portal, Paramètres page: Google connection status (no Google account in dev mode)."""
from playwright.sync_api import expect

from helpers.auth import login_as


def test_google_status_without_token(page):
    page.goto("/bureau/parametres")
    login_as(page, "admin")
    expect(page.locator("#google-status-badge")).to_contain_text("Non connecté")
    expect(page.locator("#google-account-email")).to_have_text("Non configuré")
    expect(page.locator("#google-db-mode")).to_contain_text("Firestore")

    page.locator("#btn-google-test").click()
    expect(page.locator("#google-test-results")).to_be_visible()
    expect(page.locator("#google-test-details")).to_contain_text("🔴 Jeton OAuth2")
