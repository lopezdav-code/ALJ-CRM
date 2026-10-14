"""Mobile app, coach: create, edit, delete and archive competitions."""
import datetime

from playwright.sync_api import expect

from helpers.data import eventually, unique_name
from helpers.mobile import accept_dialogs, competition_card, open_app


def _iso(days: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def test_create_competition(mobile_page, test_data):
    page = open_app(mobile_page)
    nom = unique_name("E2E Create")
    page.locator("#f-open-create").click()
    page.locator("#f-nom").fill(nom)
    page.locator("#f-idffme").fill("EVT-E2E-1")
    page.locator("#f-date").fill("2027-03-14")
    page.locator("#btn-2jours").click()
    expect(page.locator("#f-date-fin")).to_have_value("2027-03-15")
    page.locator("#f-prix").fill("18")
    page.locator("#f-coach1").select_option(label="Severus Snape")
    page.locator("#f-coach2").select_option(label="Minerva McGonagall")
    page.locator("#f-create").click()

    card = competition_card(page, nom)
    expect(card).to_contain_text("EVT-E2E-1")
    expect(card).to_contain_text("14/03/2027 → 15/03/2027")
    expect(card).to_contain_text("18.00 €")
    expect(card).to_contain_text("Coachs : Severus Snape, Minerva McGonagall")
    expect(page.locator("#comp-form-card")).to_be_hidden()

    def stored():
        doc = test_data.competition_by_name(nom)
        assert (doc["date_competition"], doc["date_fin"], doc["prix"]) == ("2027-03-14", "2027-03-15", 18)
    eventually(stored)
    page.reload()
    expect(competition_card(page, nom)).to_be_visible()


def test_name_is_required(mobile_page):
    page = open_app(mobile_page)
    page.locator("#f-open-create").click()
    page.locator("#f-create").click()
    expect(page.locator("#toast")).to_contain_text("nom de l'épreuve est obligatoire")
    expect(page.locator("#comp-form-card")).to_be_visible()


def test_edit_and_delete_competition(mobile_page, test_data):
    nom = unique_name("E2E Edit")
    test_data.create_competition(nom, date=_iso(30), prix=10)
    page = open_app(mobile_page)
    accept_dialogs(page)
    competition_card(page, nom).get_by_role("button", name="Modifier").click()
    expect(page.locator("#f-nom")).to_have_value(nom)
    renamed = unique_name("E2E Edited")
    page.locator("#f-nom").fill(renamed)
    page.locator("#f-prix").fill("22.5")
    page.locator("#f-coach1").select_option(label="Filius Flitwick")
    page.locator("#f-update").click()

    card = competition_card(page, renamed)
    expect(card).to_contain_text("22.50 €")
    expect(card).to_contain_text("Coachs : Filius Flitwick")
    expect(competition_card(page, nom)).to_have_count(0)

    card.get_by_role("button", name="Modifier").click()
    page.locator("#f-delete").click()
    expect(page.locator("#toast")).to_contain_text("Compétition supprimée")
    expect(competition_card(page, renamed)).to_have_count(0)

    def deleted():
        assert test_data.competition_by_name(renamed) is None
    eventually(deleted)


def test_archive_and_restore(mobile_page, test_data):
    nom = unique_name("E2E Archive")
    test_data.create_competition(nom, date=_iso(30))
    page = open_app(mobile_page)
    competition_card(page, nom).get_by_role("button", name="Archiver").click()
    expect(competition_card(page, nom)).to_have_count(0)

    page.locator("#comps-toggle-archived").click()
    archived = competition_card(page, nom, archived=True)
    expect(archived).to_contain_text("Archivée")
    archived.get_by_role("button", name="Désarchiver").click()
    expect(competition_card(page, nom)).to_be_visible()
    expect(competition_card(page, nom, archived=True)).to_have_count(0)


def test_archive_past_competitions(mobile_page, test_data):
    past, upcoming = unique_name("E2E Past"), unique_name("E2E Upcoming")
    test_data.create_competition(past, date=_iso(-3))
    test_data.create_competition(upcoming, date=_iso(3))
    page = open_app(mobile_page)
    accept_dialogs(page)
    button = page.locator("#comps-archive-past")
    expect(button).to_be_visible()
    button.click()
    expect(competition_card(page, past)).to_have_count(0)
    expect(competition_card(page, upcoming)).to_be_visible()
    expect(button).to_be_hidden()

    def archived():
        assert test_data.competition_by_name(past)["statut"] == "close"
    eventually(archived)
