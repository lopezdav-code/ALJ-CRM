"""Mobile app, coach: competitors of a competition (selection, payment counters, cancellation)."""
import pytest
from playwright.sync_api import expect

from helpers.data import eventually, unique_name
from helpers.mobile import open_app, open_participants, participant_card


@pytest.fixture(scope="module")
def members(test_data):
    """Competition-group members by role in the fixture competition. Every counter gets a different
    value (participe 3, en attente 2, payé 1) so that mixing two of them up cannot go unnoticed."""
    found = test_data.members(competition_only=True)
    assert len(found) >= 5, "the seed creates competition-group members"
    return {"paid": found[0], "unpaid": found[1], "unpaid_2": found[2], "invited": found[3], "outsider": found[4]}


@pytest.fixture
def competition(test_data, members):
    listed = [members[k]["id"] for k in ("paid", "unpaid", "unpaid_2", "invited")]
    nom = unique_name("E2E Participants")
    cid = test_data.create_competition(nom, date="2027-05-01", prix=12, participants=listed, selected=listed[:3])
    test_data.mark_paid(cid, members["paid"]["id"], 12.0)
    return {"id": cid, "nom": nom}


def _participant(test_data, competition, member) -> dict:
    doc = test_data.competition(competition["id"])
    return next(p for p in doc["participants"] if p["adherent_id"] == member["id"])


def test_counters_and_filters(mobile_page, competition, members):
    page = open_app(mobile_page)
    open_participants(page, competition["nom"])
    expect(page.locator("#p-kpi-participe")).to_have_text("3")
    expect(page.locator("#p-kpi-attente")).to_have_text("2")
    expect(page.locator("#p-kpi-paye")).to_have_text("1")
    expect(page.locator("#p-list .card")).to_have_count(4)
    expect(participant_card(page, members["paid"])).to_contain_text("Payé")
    expect(participant_card(page, members["unpaid"])).to_contain_text("En attente")
    expect(participant_card(page, members["invited"])).to_contain_text("Non invité")

    page.locator("#p-chip-selected").click()
    expect(page.locator("#p-list .card")).to_have_count(3)
    page.locator("#p-chip-unpaid").click()
    expect(page.locator("#p-list .card")).to_have_count(2)
    expect(participant_card(page, members["paid"])).to_have_count(0)
    page.locator("#p-chip-all").click()
    expect(page.locator("#p-list .card")).to_have_count(4)


def test_select_invited_member(mobile_page, test_data, competition, members):
    invited = members["invited"]
    page = open_app(mobile_page)
    open_participants(page, competition["nom"])
    participant_card(page, invited).locator(".switch").click()
    expect(page.locator("#p-kpi-participe")).to_have_text("4")
    expect(page.locator("#p-kpi-attente")).to_have_text("3")
    expect(participant_card(page, invited)).to_contain_text("En attente")
    def stored():
        doc = _participant(test_data, competition, invited)
        assert (doc["selectionne"], doc["statut_paiement"]) == (True, "en_attente")
    eventually(stored)


def test_unselecting_paid_member_needs_a_decision(mobile_page, test_data, competition, members):
    paid = members["paid"]
    page = open_app(mobile_page)
    open_participants(page, competition["nom"])
    participant_card(page, paid).locator(".switch").click()
    modal = page.locator("#cancel-modal")
    expect(modal).to_be_visible()
    expect(modal).to_contain_text("12.00 €")

    page.locator("#cm-ok").click()
    expect(page.locator("#toast")).to_contain_text("commentaire est obligatoire")
    page.locator("input[name='cm-choice'][value='annule_perdu']").check()
    page.locator("#cm-note").fill("Injured")
    page.locator("#cm-ok").click()

    expect(modal).to_be_hidden()
    expect(participant_card(page, paid)).to_contain_text("Annulé — perdu")
    expect(participant_card(page, paid)).to_contain_text("Injured")
    def stored():
        doc = _participant(test_data, competition, paid)
        assert (doc["selectionne"], doc["statut_paiement"], doc["note_paiement"]) == (False, "annule_perdu", "Injured")
    eventually(stored)


def test_closing_cancel_modal_keeps_paid_member(mobile_page, competition, members):
    paid = members["paid"]
    page = open_app(mobile_page)
    open_participants(page, competition["nom"])
    participant_card(page, paid).locator(".switch").click()
    page.locator("#cancel-modal").get_by_role("button", name="Annuler").click()
    expect(participant_card(page, paid).locator("input[type=checkbox]")).to_be_checked()
    expect(participant_card(page, paid)).to_contain_text("Payé")


def test_add_member_outside_the_list(mobile_page, test_data, competition, members):
    outsider = members["outsider"]
    page = open_app(mobile_page)
    open_participants(page, competition["nom"])
    page.locator("#p-search").fill(outsider["nom"][:4])
    result = page.locator("#p-search-results .row-flex").filter(has_text=f"{outsider['nom']} {outsider['prenom']}")
    result.get_by_role("button", name="Ajouter").click()
    expect(participant_card(page, outsider)).to_be_visible()
    expect(page.locator("#p-kpi-participe")).to_have_text("4")

    def added():
        assert _participant(test_data, competition, outsider)["selectionne"] is True
    eventually(added)


def test_load_competition_group(mobile_page, test_data):
    nom = unique_name("E2E Group")
    cid = test_data.create_competition(nom, date="2027-05-02")
    group = test_data.members(competition_only=True)
    page = open_app(mobile_page)
    open_participants(page, nom)
    expect(page.locator("#p-list .card")).to_have_count(0)
    page.locator("#p-load-group").click()
    expect(page.locator("#p-list .card")).to_have_count(len(group))
    expect(page.locator("#p-kpi-participe")).to_have_text("0")

    def loaded():
        assert {p["statut_paiement"] for p in test_data.competition(cid)["participants"]} == {"non_invite"}
    eventually(loaded)

    page.locator("#p-load-group").click()
    expect(page.locator("#toast")).to_contain_text("déjà présents")
