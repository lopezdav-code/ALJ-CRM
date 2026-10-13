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


def _open(page):
    page.goto("/bureau/parametres")
    login_as(page, "admin")
    expect(page.locator("#sqlite-status-badge")).to_contain_text("Cache opérationnel")
    return page


def test_server_cache_status(page):
    status = page.request.get("/api/cloud-db/status").json()
    _open(page)
    expect(page.locator("#sqlite-file-info")).to_contain_text(f"{status['member_count']} adhérents")
    expect(page.locator("#sqlite-pending-info")).to_have_text("0 (à jour)")
    expect(page.locator("#sqlite-last-sync")).not_to_have_text("Non renseignée")


def test_incremental_update_and_full_rebuild(page):
    _open(page)
    page.locator("#btn-force-update-sqlite").click()
    expect(page.locator("#toast")).to_contain_text("synchronisée avec succès")
    report = page.locator("#sqlite-sync-report-details")
    expect(report).to_contain_text("Synchronisation réussie")
    expect(report).not_to_contain_text("reconstruction complète")

    page.on("dialog", lambda dialog: dialog.accept())
    page.get_by_text("Zone de dépannage avancée").click()  # collapsed <details>
    page.locator("#btn-full-rebuild-sqlite").click()
    expect(report).to_contain_text("(reconstruction complète)", timeout=30_000)
    # The rebuilt cache still holds every member
    status = page.request.get("/api/cloud-db/status").json()
    expect(page.locator("#sqlite-file-info")).to_contain_text(f"{status['member_count']} adhérents")
    assert status["member_count"] > 20


def test_full_rebuild_needs_confirmation(page):
    _open(page)
    page.on("dialog", lambda dialog: dialog.dismiss())
    page.get_by_text("Zone de dépannage avancée").click()  # collapsed <details>
    page.locator("#btn-full-rebuild-sqlite").click()
    expect(page.locator("#sqlite-sync-report")).to_be_hidden()


def test_refresh_statuses(page):
    _open(page)
    page.locator("#settings-refresh-btn").click()
    expect(page.locator("#toast")).to_contain_text("Statuts réactualisés")
