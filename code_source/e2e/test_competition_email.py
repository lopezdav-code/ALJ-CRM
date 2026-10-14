"""E-mail to the competitors of a competition: sent by the server, captured by Mailpit."""
import re

import pytest
from playwright.sync_api import expect

from helpers.bureau import open_competitions, select_competition
from helpers.data import unique_name
from helpers.mobile import accept_dialogs, open_app, open_participants


@pytest.fixture
def competition(test_data):
    """Two selected competitors with an e-mail address, one invited only."""
    members = [m for m in test_data.members(competition_only=True) if "@" in (m.get("email") or "")][:3]
    assert len(members) == 3, "the seed gives most members an e-mail address"
    nom = unique_name("E2E Mail")
    test_data.create_competition(nom, date="2027-09-18", prix=9, participants=[m["id"] for m in members],
                                 selected=[m["id"] for m in members[:2]])
    return {"nom": nom, "selected": members[:2], "invited": members[2]}


def _assert_sent_to_selected(mailpit, competition):
    sent = mailpit.wait_for(f'subject:"{competition["nom"]}"', count=2)
    recipients = sorted(m["To"][0]["Address"] for m in sent)
    assert recipients == sorted(m["email"].lower() for m in competition["selected"])
    assert all(competition["nom"] in m["Subject"] for m in sent), "competition variables resolved by the server"
    assert not mailpit.messages(f'to:{competition["invited"]["email"]} subject:"{competition["nom"]}"')


def test_mobile_campaign(mobile_page, mailpit, competition):
    page = open_app(mobile_page)
    open_participants(page, competition["nom"])
    page.locator("#p-email-btn").click()
    expect(page.locator("#email-modal")).to_be_visible()
    expect(page.locator("#em-count-selected")).to_have_text("2")
    # Pre-filled from the seeded « Competition call-up » template
    expect(page.locator("#em-subject")).to_have_value(re.compile(r"\{name_competition\}"))
    page.locator("#em-submit-btn").click()
    expect(page.locator("#toast")).to_contain_text("2 e-mail(s) envoyé(s)")
    expect(page.locator("#email-modal")).to_be_hidden()
    _assert_sent_to_selected(mailpit, competition)


def test_office_campaign(page, mailpit, competition):
    open_competitions(page)
    accept_dialogs(page)
    select_competition(page, competition["nom"])
    page.locator("#btn-email-comp").click()
    expect(page.locator("#comp-email-recipients-count")).to_have_text("2")
    page.locator("#comp-email-subject").fill("Convocation {name_competition}")
    page.locator("#comp-email-send").click()
    expect(page.locator("#toast")).to_contain_text("envoyé(s) avec succès")
    _assert_sent_to_selected(mailpit, competition)
