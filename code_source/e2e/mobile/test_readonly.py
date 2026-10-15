"""Mobile app, read-only account: competitions and competitors visible, nothing editable."""
from playwright.sync_api import expect

from helpers.data import unique_name
from helpers.mobile import SEEDED_COMPETITION, competition_card, open_app, open_participants


def test_consultation_tabs_and_competitions(mobile_page):
    page = open_app(mobile_page, role="readonly")
    for tab in ("comps", "participants"):
        expect(page.locator(f"nav button[data-page='{tab}']")).to_be_visible()
    for tab in ("helloasso", "coaches", "balance"):
        expect(page.locator(f"nav button[data-page='{tab}']")).to_be_hidden()

    expect(page.locator("#f-open-create")).to_be_hidden()
    expect(page.locator("#comps-archive-past")).to_be_hidden()
    card = competition_card(page, SEEDED_COMPETITION)
    expect(card.get_by_role("button", name="Voir détail")).to_be_visible()
    expect(card.get_by_role("button", name="Modifier")).to_have_count(0)
    expect(card.get_by_role("button", name="Archiver")).to_have_count(0)


def test_competitors_cannot_be_changed(mobile_page, test_data):
    members = test_data.members(competition_only=True)[:2]
    nom = unique_name("E2E Readonly")
    test_data.create_competition(nom, date="2027-07-01", participants=[m["id"] for m in members],
                                 selected=[members[0]["id"]])
    page = open_app(mobile_page, role="readonly")
    open_participants(page, nom)
    checkboxes = page.locator("#p-list .card input[type=checkbox]")
    expect(checkboxes).to_have_count(2)
    for i in range(2):
        expect(checkboxes.nth(i)).to_be_disabled()
    for button in ("#p-load-group", "#p-email-btn", "#p-edit-btn"):
        expect(page.locator(button)).to_be_hidden()
    expect(page.locator("#p-search-card")).to_be_hidden()
