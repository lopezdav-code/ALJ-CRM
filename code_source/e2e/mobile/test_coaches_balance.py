"""Mobile app, coach: coaches management and the athletes' payment balance."""
from playwright.sync_api import expect

from helpers.data import eventually, unique_name
from helpers.mobile import accept_dialogs, competition_card, go_to, open_app


def _coach_card(page, nom):
    return page.locator("#coaches-list .card").filter(has=page.locator(".m-name").get_by_text(nom, exact=True))


def test_create_rename_delete_coach(mobile_page, test_data):
    page = open_app(mobile_page)
    accept_dialogs(page)
    go_to(page, "coaches")
    nom = unique_name("E2E Coach")
    page.locator("#f-coach-nom").fill(nom)
    page.locator("#f-coach-create").click()
    # The card shows before the save completes, which then resets the form: wait for the confirmation
    expect(page.locator("#toast")).to_contain_text("Coach ajouté")
    expect(_coach_card(page, nom)).to_be_visible()

    _coach_card(page, nom).click()
    expect(page.locator("#f-coach-nom")).to_have_value(nom)
    renamed = unique_name("E2E Coach renamed")
    page.locator("#f-coach-nom").fill(renamed)
    page.locator("#f-coach-update").click()
    expect(_coach_card(page, renamed)).to_be_visible()
    expect(_coach_card(page, nom)).to_have_count(0)

    page.locator("#f-coach-delete").click()
    expect(_coach_card(page, renamed)).to_have_count(0)

    def deleted():
        assert all(c["nom"] != renamed for c in test_data.coaches())
    eventually(deleted)


def test_coach_changes_reach_competitions(mobile_page, test_data):
    """A renamed coach shows under the new name on their competitions; a deleted one leaves them."""
    coach = unique_name("E2E Coach")
    coach_id = test_data.create_coach(coach)
    comp = unique_name("E2E Coached")
    test_data.create_competition(comp, date="2027-06-01", coach_ids=[coach_id])
    page = open_app(mobile_page)
    accept_dialogs(page)
    expect(competition_card(page, comp)).to_contain_text(f"Coachs : {coach}")

    go_to(page, "coaches")
    _coach_card(page, coach).click()
    expect(page.locator("#coach-competitions-list")).to_contain_text(comp)
    renamed = unique_name("E2E Coach renamed")
    page.locator("#f-coach-nom").fill(renamed)
    page.locator("#f-coach-update").click()
    go_to(page, "comps")
    expect(competition_card(page, comp)).to_contain_text(f"Coachs : {renamed}")

    go_to(page, "coaches")
    _coach_card(page, renamed).click()
    page.locator("#f-coach-delete").click()
    go_to(page, "comps")
    expect(competition_card(page, comp)).to_contain_text("Aucun coach")

    def unassigned():
        assert test_data.competition_by_name(comp)["coach_ids"] == []
    eventually(unassigned)


def test_balance_of_an_athlete(mobile_page, test_data):
    member = test_data.members(competition_only=True)[4]
    due, paid_comp = unique_name("E2E Due"), unique_name("E2E Paid")
    test_data.create_competition(due, date="2027-06-03", prix=15, participants=[member["id"]], selected=[member["id"]])
    paid_id = test_data.create_competition(paid_comp, date="2027-06-04", prix=10, participants=[member["id"]],
                                           selected=[member["id"]])
    test_data.mark_paid(paid_id, member["id"], 10.0)

    page = open_app(mobile_page)
    go_to(page, "balance")
    page.locator("#bal-search").fill(f"{member['nom']} {member['prenom']}")
    row = page.locator("#bal-list .card").filter(has_text=member["prenom"])
    expect(row).to_have_count(1)
    expect(row).to_contain_text(due)
    expect(row).to_contain_text(paid_comp)
    # Other competitions of the seed can add to the totals: check only what this test adds up to
    expect(row).to_contain_text("Non équilibré")
