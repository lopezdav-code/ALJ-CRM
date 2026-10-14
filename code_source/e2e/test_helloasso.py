"""HelloAsso payments: sync from the (fake) API, automatic and manual links, ignored lines,
webhook notifications and the membership dashboard."""
import re
import uuid

import pytest
from playwright.sync_api import expect

from helpers import helloasso
from helpers.bureau import go_to as bureau_go_to, open_competitions
from helpers.data import eventually, unique_name
from helpers.helloasso import item
from helpers.mobile import go_to, open_app, open_participants, participant_card

KNOWN_BUG_A6 = pytest.mark.xfail(strict=True, reason="bug A6: the office page stores the ids as strings and "
                                                      "reads the order reference from `order.id`")


@pytest.fixture
def setup(test_data, fake_helloasso):
    """A competition with two invited members (with a licence) and three HelloAsso payments:
    one auto-linkable (licence + competition number), two that need a coach."""
    members = [m for m in test_data.members(competition_only=True) if m.get("licence_ffme")][:2]
    assert len(members) == 2, "the seed gives most members a licence number"
    number = "E2E-" + uuid.uuid4().hex[:6].upper()
    nom = unique_name("E2E HelloAsso")
    cid = test_data.create_competition(nom, date="2027-11-05", prix=15, id_ffme=number,
                                       participants=[m["id"] for m in members], selected=[members[0]["id"]])
    tag = uuid.uuid4().hex[:6]
    auto = item(members[0]["prenom"], members[0]["nom"], 15, licence=members[0]["licence_ffme"],
                competition_number=number)
    unknown_payer = item("Mundungus", f"Fletcher{tag}", 15, competition_number=number)
    no_competition = item("Gilderoy", f"Lockhart{tag}", 7.5)
    fake_helloasso.set([auto, unknown_payer, no_competition])
    return {"competition": {"id": cid, "nom": nom}, "members": members, "tag": tag,
            "auto": auto, "unknown_payer": unknown_payer, "no_competition": no_competition}


def _sync_on_phone(page):
    go_to(page, "helloasso")
    page.locator("#ha-btn-sync").click()
    expect(page.locator("#toast")).to_contain_text("Synchro terminée : 3 article(s)", timeout=20_000)


def _item_card(page, ha_item):
    """Card of a HelloAsso item, by its order number (members get payments in several tests)."""
    page.locator("#ha-chip-all").click()
    page.locator("#ha-search").fill(str(ha_item["order"]["id"]))
    return page.locator("#ha-items-list > .card").filter(has_text=re.compile(rf"Commande #{ha_item['order']['id']}\b"))


def _participant(test_data, setup, member) -> dict:
    return next(p for p in test_data.competition(setup["competition"]["id"])["participants"]
                if p["adherent_id"] == member["id"])


def test_sync_links_payment_automatically(mobile_page, test_data, setup):
    page = open_app(mobile_page)
    _sync_on_phone(page)
    expect(_item_card(page, setup["auto"])).to_contain_text("Rattaché")
    expect(_item_card(page, setup["unknown_payer"])).to_contain_text("En attente")
    expect(_item_card(page, setup["no_competition"])).to_contain_text("En attente")

    go_to(page, "comps")
    open_participants(page, setup["competition"]["nom"])
    paid = participant_card(page, setup["members"][0])
    expect(paid).to_contain_text("Payé")

    def linked():
        assert test_data.helloasso_item(setup["auto"]["id"])["source"] == "auto"
    eventually(linked)


def test_manual_link_marks_member_paid(mobile_page, test_data, setup):
    member = setup["members"][1]
    page = open_app(mobile_page)
    _sync_on_phone(page)
    card = _item_card(page, setup["unknown_payer"])
    card.get_by_role("button", name="Rattacher").click()
    page.locator("#ha-modal-comp-select").select_option(str(setup["competition"]["id"]))
    page.locator("#ha-modal-adh-select").select_option(str(member["id"]))
    page.locator("#ha-modal-comment").fill("Paid by an uncle")
    page.locator("#ha-modal-save-btn").click()
    expect(page.locator("#toast")).to_contain_text("rattaché avec succès")
    expect(card).to_contain_text("Rattaché")
    expect(card).to_contain_text("manuel")

    go_to(page, "comps")
    open_participants(page, setup["competition"]["nom"])
    expect(participant_card(page, member)).to_contain_text("Payé")

    def stored():
        doc = test_data.helloasso_item(setup["unknown_payer"]["id"])
        assert (doc["competition_id"], doc["adherent_id"], doc["source"]) == (setup["competition"]["id"], member["id"], "manuel")
        participant = _participant(test_data, setup, member)
        assert (participant["montant_paye"], participant["commande_helloasso"]) == (15, str(setup["unknown_payer"]["order"]["id"]))
    eventually(stored)


def test_ignore_and_restore_a_payment(mobile_page, test_data, setup):
    page = open_app(mobile_page)
    _sync_on_phone(page)
    card = _item_card(page, setup["no_competition"])
    card.get_by_role("button", name="Rattacher").click()
    page.locator("#ha-modal-ignore-btn").click()
    expect(page.locator("#toast")).to_contain_text("Indiquez un commentaire")
    page.locator("#ha-modal-comment").fill("Shop purchase, not a competition")
    page.locator("#ha-modal-ignore-btn").click()
    expect(page.locator("#toast")).to_contain_text("Ligne ignorée")

    # Hidden from the list while « hide ignored » is ticked (default)
    expect(card).to_have_count(0)
    page.locator("#ha-chip-ignored").click()
    expect(card).to_contain_text("Ignoré")

    def ignored():
        doc = test_data.helloasso_item(setup["no_competition"]["id"])
        assert (doc["ignore"], doc["ignore_motif"]) == (True, "Shop purchase, not a competition")
    eventually(ignored)

    card.get_by_role("button", name="Détails").click()
    page.locator("#ha-modal-ignore-btn").click()
    expect(page.locator("#toast")).to_contain_text("n'est plus ignorée")

    def restored():
        assert test_data.helloasso_item(setup["no_competition"]["id"])["ignore"] is False
    eventually(restored)


def test_resync_keeps_coach_decisions(mobile_page, test_data, setup):
    """A new sync rewrites HelloAsso's fields only: manual links and ignored lines survive."""
    member = setup["members"][1]
    page = open_app(mobile_page)
    _sync_on_phone(page)
    _item_card(page, setup["unknown_payer"]).get_by_role("button", name="Rattacher").click()
    page.locator("#ha-modal-comp-select").select_option(str(setup["competition"]["id"]))
    page.locator("#ha-modal-adh-select").select_option(str(member["id"]))
    page.locator("#ha-modal-save-btn").click()
    expect(page.locator("#toast")).to_contain_text("rattaché avec succès")
    _item_card(page, setup["no_competition"]).get_by_role("button", name="Rattacher").click()
    page.locator("#ha-modal-comment").fill("Duplicate")
    page.locator("#ha-modal-ignore-btn").click()
    expect(page.locator("#toast")).to_contain_text("Ligne ignorée")

    page.locator("#ha-btn-sync").click()
    expect(page.locator("#toast")).to_contain_text("Synchro terminée", timeout=20_000)

    def kept():
        linked = test_data.helloasso_item(setup["unknown_payer"]["id"])
        assert (linked["source"], linked["adherent_id"]) == ("manuel", member["id"])
        assert test_data.helloasso_item(setup["no_competition"]["id"])["ignore"] is True
    eventually(kept)


def test_webhook_marks_member_paid(mobile_page, page, test_data, setup):
    """HelloAsso notifies an order: the server re-reads it from the API and links it."""
    order_id = setup["auto"]["order"]["id"]
    refused = page.request.post("/webhooks/helloasso?token=wrong", data={"eventType": "Order", "data": {"id": order_id}})
    assert refused.status == 401

    accepted = page.request.post(f"/webhooks/helloasso?token={helloasso.WEBHOOK_TOKEN}",
                                 data={"eventType": "Order", "data": {"id": order_id}})
    assert accepted.ok, accepted.text()
    assert accepted.json()["verified"] == "api"

    phone = open_app(mobile_page)
    open_participants(phone, setup["competition"]["nom"])
    expect(participant_card(phone, setup["members"][0])).to_contain_text("Payé")
    go_to(phone, "helloasso")
    expect(_item_card(phone, setup["auto"])).to_contain_text("Rattaché")


def test_webhook_ignores_other_forms(page, fake_helloasso):
    shop = item("Neville", "Longbottom", 5, form_slug="boutique-e2e")
    fake_helloasso.set([shop])
    answer = page.request.post(f"/webhooks/helloasso?token={helloasso.WEBHOOK_TOKEN}",
                               data={"eventType": "Order", "data": {"id": shop["order"]["id"]}})
    assert answer.ok and answer.json()["status"] == "ignored"


def test_office_sync_and_filters(page, setup):
    open_competitions(page)
    bureau_go_to(page, "helloasso")
    page.locator("#btn-sync-ha-global").click()
    expect(page.locator("#toast")).to_contain_text("3 articles traités", timeout=20_000)
    page.locator("#ha-search-input").fill(setup["tag"])
    rows = page.locator("#ha-table-tbody tr[data-item-id]")
    expect(rows).to_have_count(2)
    page.locator("#ha-filter-linked").click()
    expect(rows).to_have_count(0)
    page.locator("#ha-filter-pending").click()
    expect(rows).to_have_count(2)


def test_office_manual_link(page, test_data, setup):
    member = setup["members"][1]
    open_competitions(page)
    bureau_go_to(page, "helloasso")
    page.locator("#btn-sync-ha-global").click()
    expect(page.locator("#toast")).to_contain_text("articles traités", timeout=20_000)
    page.locator("#ha-search-input").fill(setup["unknown_payer"]["user"]["lastName"])
    page.locator("#ha-table-tbody tr[data-item-id] .btn-open-attach").click()
    page.locator("#attach-comp-select").select_option(str(setup["competition"]["id"]))
    page.locator("#attach-adh-select").select_option(str(member["id"]))
    page.locator("#ha-attach-submit").click()
    expect(page.locator("#toast")).to_contain_text("Rattachement enregistré")

    def paid():
        participant = _participant(test_data, setup, member)
        assert (participant["statut_paiement"], participant["montant_paye"]) == ("paye", 15)
    eventually(paid)


@KNOWN_BUG_A6
def test_office_manual_link_is_stored_like_the_phone(page, test_data, setup):
    member = setup["members"][1]
    open_competitions(page)
    bureau_go_to(page, "helloasso")
    page.locator("#btn-sync-ha-global").click()
    expect(page.locator("#toast")).to_contain_text("articles traités", timeout=20_000)
    page.locator("#ha-search-input").fill(setup["unknown_payer"]["user"]["lastName"])
    page.locator("#ha-table-tbody tr[data-item-id] .btn-open-attach").click()
    page.locator("#attach-comp-select").select_option(str(setup["competition"]["id"]))
    page.locator("#attach-adh-select").select_option(str(member["id"]))
    page.locator("#ha-attach-submit").click()
    expect(page.locator("#toast")).to_contain_text("Rattachement enregistré")

    def stored():
        doc = test_data.helloasso_item(setup["unknown_payer"]["id"])
        assert (doc["competition_id"], doc["adherent_id"]) == (setup["competition"]["id"], member["id"])
        assert _participant(test_data, setup, member)["commande_helloasso"] == str(setup["unknown_payer"]["order"]["id"])
    eventually(stored)


def test_membership_dashboard(page, fake_helloasso):
    """/api/dashboard (membership campaign, CAMPAIGN_SLUG) — no page uses it on the web yet."""
    members = [item("Luna", "Lovegood", 180, form_slug=helloasso.MEMBERSHIP_FORM, item_type="Membership",
                    name="Adulte loisir"),
               item("Cho", "Chang", 150, form_slug=helloasso.MEMBERSHIP_FORM, item_type="Membership",
                    name="Jeune compétition")]
    fake_helloasso.set(members)
    data = page.request.get("/api/dashboard").json()
    assert data["campaign"]["formSlug"] == helloasso.MEMBERSHIP_FORM
    assert data["total_inscrits"] == 2
    assert sorted(t["name"] for t in data["tariffs"]) == ["Adulte loisir", "Jeune compétition"]
    assert {p["amount"] for p in data["participants"]} == {180, 150}
