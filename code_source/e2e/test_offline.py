"""Mobile app without network: changes made offline are kept locally and sent when the
connection comes back (Firestore offline persistence of web/competitions.html).

Once the pages go through the API (docs/plan_api_only_front.md, offline = read-only snapshot),
this test is expected to change: writes will then be refused offline."""
from playwright.sync_api import expect

from helpers.data import unique_name
from helpers.mobile import competition_card, open_app


def test_competition_created_offline_is_sent_later(mobile_page, mobile_context, test_data):
    page = open_app(mobile_page)
    nom = unique_name("E2E Offline")
    mobile_context.set_offline(True)
    try:
        page.locator("#f-open-create").click()
        page.locator("#f-nom").fill(nom)
        page.locator("#f-date").fill("2027-12-04")
        page.locator("#f-create").click()
        # Shown at once from the local cache, not yet on the server
        expect(competition_card(page, nom)).to_be_visible()
        assert test_data.competition_by_name(nom) is None
    finally:
        mobile_context.set_offline(False)

    # Back online: the pending write reaches Firestore and the app confirms it
    expect(page.locator("#toast")).to_contain_text("Compétition créée", timeout=30_000)
    assert test_data.competition_by_name(nom)["date_competition"] == "2027-12-04"
