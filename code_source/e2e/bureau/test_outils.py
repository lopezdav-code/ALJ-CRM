"""Office portal, Outils page: members map, pivot table, Google connection status."""
import json

from playwright.sync_api import expect

from helpers.auth import login_as


def _open(page, role="admin"):
    page.goto("/bureau/outils")
    login_as(page, role)
    return page


def test_members_map(page):
    """Map of the members' addresses (Leaflet). The e2e setup pre-fills the geocache, so the
    server never calls Nominatim."""
    _open(page)
    expect(page.locator("#iframe-map")).to_be_visible(timeout=30_000)
    frame = page.frame_locator("#iframe-map")
    expect(frame.locator(".leaflet-container")).to_be_visible()
    # Members are shown as markers grouped in clusters
    clusters = frame.locator(".marker-cluster, .leaflet-marker-icon")
    expect(clusters.first).to_be_visible(timeout=15_000)
    assert "nominatim" not in page.request.get("/map").text().lower()


def test_pivot_table_by_season(page):
    _open(page)
    page.locator("#tab-btn-pivot").click()
    expect(page.locator("#iframe-pivot")).to_be_visible(timeout=30_000)
    seasons = page.locator("#pivot-season-select option")
    expect(seasons).to_have_count(3)  # all seasons + the two seeded ones
    frame = page.frame_locator("#iframe-pivot")
    expect(frame.locator(".pvtTable, .pvtUi").first).to_be_visible(timeout=15_000)

    with page.expect_response(lambda r: "/pivot?season=2025-2026" in r.url and r.ok):
        page.locator("#pivot-season-select").select_option("2025-2026")
    expect(page.locator("#iframe-pivot")).to_be_visible()
    expect(frame.locator(".pvtTable, .pvtUi").first).to_be_visible()


def test_google_status_without_token(page):
    _open(page)
    page.locator("#tab-btn-google").click()
    expect(page.locator("#google-status-badge")).to_contain_text("Non connecté")
    expect(page.locator("#google-account-email")).to_have_text("Non configuré")
    expect(page.locator("#google-db-mode")).to_contain_text("Firestore")

    page.locator("#btn-google-test").click()
    expect(page.locator("#google-test-results")).to_be_visible()
    expect(page.locator("#google-test-details")).to_contain_text("🔴 Jeton OAuth2")
    expect(page.locator("#toast")).to_contain_text("ont échoué")


def test_refresh_button(page):
    _open(page)
    expect(page.locator("#iframe-map")).to_be_visible(timeout=30_000)
    page.locator("#tools-refresh-btn").click()
    expect(page.locator("#toast")).to_contain_text("Carte réactualisée")


def test_expired_google_token_warning(page):
    """Every office page warns when the club's Google token has expired (alj-shell.js)."""
    page.route("**/api/auth/google/status", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"status": "expired", "user_email": "office@hogwarts.example"})))
    page.goto("/bureau/")
    login_as(page, "admin")
    expect(page.locator("#google-auth-warning")).to_be_visible()


def test_no_warning_when_token_is_fine(page):
    page.goto("/bureau/")
    login_as(page, "admin")
    expect(page.locator("#content")).to_be_visible()
    expect(page.locator("#google-auth-warning")).to_be_hidden()
