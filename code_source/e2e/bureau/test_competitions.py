"""Office portal, admin: competitions, competitors, CSV exports, season balance and coaches."""
import csv
import datetime
import io

import pytest
from playwright.sync_api import expect

from helpers.bureau import (
    coach_card,
    competition_card,
    go_to,
    open_competitions,
    participant_row,
    select_competition,
)
from helpers.data import unique_name
from helpers.mobile import SEEDED_COMPETITION, accept_dialogs

PAST_SEEDED = "Diagon Alley Bouldering Cup"
# Known bug A6 (docs/plan_api_only_front.md, appendix A): this page reads the `adherents` projection
# with the wrong field names (last_name/first_name/email_primary instead of nom/prenom/email), so
# member search and e-mail recipients come back empty. Fixed by the API rewrite of the page:
# strict, so these tests fail (XPASS) once the fix is merged, as a reminder to drop the marker.
KNOWN_BUG_A6 = pytest.mark.xfail(strict=True, reason="bug A6: wrong field names on the `adherents` projection")


def _iso(days: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days)).isoformat()


def _read_csv(download, folder) -> list:
    # save_as(): path() is not available with a remote browser (E2E_PLAYWRIGHT_WS)
    target = folder / download.suggested_filename
    download.save_as(target)
    return list(csv.reader(io.StringIO(target.read_text(encoding="utf-8-sig")), delimiter=";"))


@pytest.fixture(scope="module")
def members(test_data):
    return test_data.members(competition_only=True)[:3]


def test_create_competition(page, test_data):
    open_competitions(page)
    nom = unique_name("E2E Office")
    page.locator("#btn-add-comp").click()
    page.locator("#f-nom").fill(nom)
    page.locator("#f-date").fill("2027-04-10")
    page.locator("#f-lieu").fill("Saint-Étienne")
    page.locator("#f-type").select_option("Difficulté")
    page.locator("#f-prix").fill("17")
    page.locator("#f-coaches-box label").filter(has_text="Severus Snape").locator("input").check()
    page.locator("#comp-modal-submit").click()

    expect(page.locator("#comp-form-modal")).to_be_hidden()
    card = competition_card(page, nom)
    expect(card).to_contain_text("Saint-Étienne")
    expect(card).to_contain_text("Difficulté")
    workspace = select_competition(page, nom)
    expect(workspace).to_contain_text("17 €")
    expect(workspace).to_contain_text("Severus Snape")
    stored = test_data.competition_by_name(nom)
    assert (stored["lieu"], stored["type"], stored["prix"]) == ("Saint-Étienne", "Difficulté", 17)


def test_edit_and_delete_competition(page, test_data):
    nom = unique_name("E2E Office edit")
    test_data.create_competition(nom, date=_iso(20))
    open_competitions(page)
    accept_dialogs(page)
    select_competition(page, nom)
    page.locator("#btn-edit-comp").click()
    expect(page.locator("#f-nom")).to_have_value(nom)
    renamed = unique_name("E2E Office edited")
    page.locator("#f-nom").fill(renamed)
    page.locator("#f-lieu").fill("Lyon")
    page.locator("#comp-modal-submit").click()
    expect(competition_card(page, renamed)).to_contain_text("Lyon")

    select_competition(page, renamed)
    page.locator("#btn-del-comp").click()
    expect(competition_card(page, renamed)).to_have_count(0)
    assert test_data.competition_by_name(renamed) is None


def test_search_and_date_filters(page):
    open_competitions(page)
    page.locator("#comp-search-input").fill("hogwarts lead")
    expect(page.locator("#comps-list-container .comp-card")).to_have_count(1)
    page.locator("#comp-search-input").fill("")

    page.locator("#chip-filter-past").click()
    expect(competition_card(page, PAST_SEEDED)).to_be_visible()
    expect(competition_card(page, SEEDED_COMPETITION)).to_have_count(0)
    page.locator("#chip-filter-upcoming").click()
    expect(competition_card(page, SEEDED_COMPETITION)).to_be_visible()
    expect(competition_card(page, PAST_SEEDED)).to_have_count(0)
    page.locator("#chip-filter-all").click()
    expect(competition_card(page, PAST_SEEDED)).to_be_visible()


def test_competitors_selection_and_attendance(page, test_data, members):
    selected, invited, _ = members
    nom = unique_name("E2E Office parts")
    cid = test_data.create_competition(nom, date=_iso(25), participants=[selected["id"], invited["id"]],
                                       selected=[selected["id"]])
    open_competitions(page)
    workspace = select_competition(page, nom)
    expect(page.locator("#parts-tbody tr[data-aid]")).to_have_count(2)

    participant_row(page, invited).locator(".part-select-chk").check()
    expect(workspace.locator(".kpi-card").first).to_contain_text("2")
    participant_row(page, invited).locator(".part-present-chk").check()
    expect(workspace.locator(".kpi-card").nth(3)).to_contain_text("1 / 2")
    stored = {p["adherent_id"]: p for p in test_data.competition(cid)["participants"]}
    assert stored[invited["id"]]["selectionne"] is True and stored[invited["id"]]["present"] is True


@KNOWN_BUG_A6
def test_register_a_member(page, test_data, members):
    outsider = members[2]
    nom = unique_name("E2E Office register")
    cid = test_data.create_competition(nom, date=_iso(25))
    open_competitions(page)
    workspace = select_competition(page, nom)
    workspace.locator(".sub-tab-btn[data-subtab='add_adh']").click()
    page.locator("#adh-search-input").fill(outsider["nom"][:4].lower())
    result = page.locator("#adh-results-box .card").filter(has_text=outsider["prenom"])
    result.locator(".add-adh-btn").click(timeout=5_000)
    expect(page.locator("#toast")).to_contain_text("inscrit avec succès")
    workspace.locator(".sub-tab-btn[data-subtab='participants']").click()
    expect(participant_row(page, outsider)).to_be_visible()
    [stored] = test_data.competition(cid)["participants"]
    assert (stored["adherent_id"], stored["nom"], stored["prenom"]) == (outsider["id"], outsider["nom"], outsider["prenom"])


def test_competition_csv_export(page, test_data, members, tmp_path):
    nom = unique_name("E2E Office csv")
    test_data.create_competition(nom, date=_iso(26), participants=[m["id"] for m in members],
                                 selected=[members[0]["id"]])
    open_competitions(page)
    select_competition(page, nom)
    with page.expect_download() as info:
        page.locator("#btn-export-comp-csv").click()
    rows = _read_csv(info.value, tmp_path)
    assert rows[0][:3] == ["Nom", "Prénom", "N° Licence"]
    assert len(rows) == 1 + len(members)
    participe = rows[0].index("Participe")
    assert sorted(r[participe] for r in rows[1:]) == ["Non", "Non", "Oui"]


def test_season_balance(page, test_data, members, tmp_path):
    member = members[0]
    nom = unique_name("E2E Office bilan")
    test_data.create_competition(nom, date=_iso(27), prix=14, participants=[member["id"]], selected=[member["id"]])
    open_competitions(page)
    go_to(page, "bilan")
    expect(page.locator("#section-bilan")).to_be_visible()
    expect(page.locator("#bilan-season-select option")).not_to_have_count(0)
    expect(page.locator("#bilan-kpi-athletes")).not_to_have_text("0")

    page.locator("#bilan-search-input").fill(member["prenom"])
    athlete = page.locator("#bilan-athletes-list-container .comp-card").filter(has_text=member["prenom"]).first
    athlete.click()
    expect(page.locator("#bilan-athlete-workspace")).to_contain_text(nom)

    with page.expect_download() as info:
        page.locator("#btn-export-bilan-csv").click()
    assert len(_read_csv(info.value, tmp_path)) > 1


def test_coaches_tab(page, test_data):
    nom = unique_name("E2E Office coach")
    open_competitions(page)
    accept_dialogs(page)
    go_to(page, "coachs")
    page.locator("#coach-new-name").fill(nom)
    page.locator("#btn-save-coach").click()
    expect(coach_card(page, nom)).to_be_visible()
    coach_card(page, nom).click()
    expect(page.locator("#coach-workspace")).to_contain_text(f"Coach : {nom}")
    page.locator("#btn-del-coach").click()
    expect(coach_card(page, nom)).to_have_count(0)

    coach_card(page, "Severus Snape").click()
    workspace = page.locator("#coach-workspace")
    workspace.locator(".card .card").filter(has_text=SEEDED_COMPETITION).locator(".btn-goto-comp").click()
    expect(page.locator("#section-competitions")).to_be_visible()
    expect(page.locator("#comp-workspace")).to_contain_text(SEEDED_COMPETITION)


def test_coach_cannot_edit_in_office(page):
    open_competitions(page, role="coach")
    expect(page.locator("#btn-add-comp")).to_have_count(0)
    workspace = select_competition(page, SEEDED_COMPETITION)
    expect(workspace.locator("#btn-edit-comp")).to_have_count(0)
    expect(workspace.locator("#btn-del-comp")).to_have_count(0)
    expect(page.locator("#parts-tbody .part-select-chk").first).to_be_disabled()


# ---------------------------------------------------------------------------
# Competitors workflow: manual payment, withdrawal (credit kept or lost), check-in
# ---------------------------------------------------------------------------
@pytest.fixture
def workflow(test_data, members):
    """A competition with a paid competitor and an unpaid one, opened by the admin."""
    paid, unpaid, _ = members
    nom = unique_name("E2E Workflow")
    cid = test_data.create_competition(nom, date=_iso(28), prix=12, participants=[paid["id"], unpaid["id"]],
                                       selected=[paid["id"], unpaid["id"]])
    test_data.mark_paid(cid, paid["id"], 12.0, order_ref="E2E-PAID")
    return {"id": cid, "nom": nom, "paid": paid, "unpaid": unpaid}


@pytest.fixture
def dialogs(page):
    """Answers confirm() boxes (accept unless told otherwise) and prompt() boxes with `text`."""
    answer = {"accept": True, "text": ""}

    def handle(dialog):
        if not answer["accept"]:
            dialog.dismiss()
        elif dialog.type == "prompt":
            dialog.accept(answer["text"])
        else:
            dialog.accept()
    page.on("dialog", handle)
    return answer


def _stored(test_data, workflow, member):
    return next(p for p in test_data.competition(workflow["id"])["participants"] if p["adherent_id"] == member["id"])


def test_manual_payment(page, test_data, workflow, dialogs):
    open_competitions(page)
    select_competition(page, workflow["nom"])
    row = participant_row(page, workflow["unpaid"])
    expect(row).to_contain_text("En attente")
    dialogs["text"] = "12,5"
    row.locator(".part-mark-paid-btn").click()
    expect(page.locator("#toast")).to_contain_text("Paiement manuel de 12.5 € enregistré")
    expect(participant_row(page, workflow["unpaid"])).to_contain_text("Payé (12.5 €)")
    stored = _stored(test_data, workflow, workflow["unpaid"])
    assert (stored["statut_paiement"], stored["montant_paye"], stored["commande_helloasso"]) == (
        "paye", 12.5, "Règlement manuel")


def test_paid_competitor_cannot_be_removed(page, workflow):
    open_competitions(page)
    select_competition(page, workflow["nom"])
    row = participant_row(page, workflow["paid"])
    expect(row).to_contain_text("Payé (12 €)")
    expect(row.locator(".part-remove-btn")).to_have_count(0)
    expect(row.locator(".part-action-select")).to_be_visible()


@pytest.mark.parametrize("decision, badge", [("annule_reporte", "Report (12 €)"), ("annule_perdu", "Annulé — perdu (12 €)")])
def test_withdrawal_of_paid_competitor(page, test_data, workflow, dialogs, decision, badge):
    open_competitions(page)
    select_competition(page, workflow["nom"])
    participant_row(page, workflow["paid"]).locator(".part-action-select").select_option(decision)
    row = participant_row(page, workflow["paid"])
    expect(row).to_contain_text(badge)
    expect(row.locator(".part-select-chk")).not_to_be_checked()
    stored = _stored(test_data, workflow, workflow["paid"])
    assert (stored["statut_paiement"], stored["selectionne"], stored["montant_paye"]) == (decision, False, 12)

    # A withdrawal entered by mistake can be undone
    row.locator(".part-restore-paid-btn").click()
    expect(participant_row(page, workflow["paid"])).to_contain_text("Payé (12 €)")
    stored = _stored(test_data, workflow, workflow["paid"])
    assert (stored["statut_paiement"], stored["selectionne"]) == ("paye", True)


def test_withdrawal_needs_confirmation(page, test_data, workflow, dialogs):
    open_competitions(page)
    select_competition(page, workflow["nom"])
    dialogs["accept"] = False
    select = participant_row(page, workflow["paid"]).locator(".part-action-select")
    select.select_option("annule_perdu")
    expect(select).to_have_value("")
    assert _stored(test_data, workflow, workflow["paid"])["statut_paiement"] == "paye"


def test_checked_in_competitor_is_locked(page, test_data, workflow):
    open_competitions(page)
    select_competition(page, workflow["nom"])
    participant_row(page, workflow["paid"]).locator(".part-present-chk").check()
    row = participant_row(page, workflow["paid"])
    expect(row).to_contain_text("Sur place")
    expect(row.locator(".part-action-select, .part-remove-btn")).to_have_count(0)
    assert _stored(test_data, workflow, workflow["paid"])["present"] is True


def test_remove_unpaid_competitor(page, test_data, workflow, dialogs):
    open_competitions(page)
    select_competition(page, workflow["nom"])
    participant_row(page, workflow["unpaid"]).locator(".part-remove-btn").click()
    expect(participant_row(page, workflow["unpaid"])).to_have_count(0)
    remaining = [p["adherent_id"] for p in test_data.competition(workflow["id"])["participants"]]
    assert remaining == [workflow["paid"]["id"]]
