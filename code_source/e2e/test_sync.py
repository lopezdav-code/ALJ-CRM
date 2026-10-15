"""Two coaches on two phones: a change made on one shows up on the other without reloading.

Today the pages listen to Firestore; once they poll the API (docs/plan_api_only_front.md, 20 s
interval) the same test checks the polling, hence the generous timeout."""
import pytest
from playwright.sync_api import expect

from helpers.data import unique_name
from helpers.mobile import competition_card, open_app, open_participants, participant_card

pytestmark = pytest.mark.slow
SYNC_TIMEOUT = 30_000


@pytest.fixture
def second_phone(new_context, playwright):
    device = {k: v for k, v in playwright.devices["Pixel 7"].items() if k != "default_browser_type"}
    return new_context(**device).new_page()


def test_new_competition_reaches_other_phone(mobile_page, second_phone):
    first, second = open_app(mobile_page), open_app(second_phone)
    nom = unique_name("E2E Sync")
    first.locator("#f-open-create").click()
    first.locator("#f-nom").fill(nom)
    first.locator("#f-date").fill("2027-10-02")
    first.locator("#f-create").click()
    expect(competition_card(second, nom)).to_be_visible(timeout=SYNC_TIMEOUT)


def test_selection_reaches_other_phone(mobile_page, second_phone, test_data):
    member = test_data.members(competition_only=True)[0]
    nom = unique_name("E2E Sync")
    test_data.create_competition(nom, date="2027-10-03", participants=[member["id"]])
    first, second = open_app(mobile_page), open_app(second_phone)
    open_participants(first, nom)
    open_participants(second, nom)
    participant_card(first, member).locator(".switch").click()
    expect(second.locator("#p-kpi-participe")).to_have_text("1", timeout=SYNC_TIMEOUT)
    expect(participant_card(second, member).locator("input[type=checkbox]")).to_be_checked()
