"""Office portal, members page: list, filters, detail, CSV export, edit, e-mail and payment certificate."""
import csv
import io
import re
import uuid

import pytest
from playwright.sync_api import expect

from helpers.members import ROWS, displayed_count, find, open_members, select
from helpers.mobile import accept_dialogs


@pytest.fixture(scope="module")
def people(test_data):
    """Seeded members of the active season, one per test that sends or changes something."""
    found = sorted(test_data.members(), key=lambda m: (m["nom"], m["prenom"]))
    assert len(found) >= 6
    return found


def test_list_search_and_detail(page, people):
    member = people[0]
    open_members(page)
    total = displayed_count(page)
    assert total > 20
    expect(page.locator(ROWS)).to_have_count(total)

    expect(find(page, member)).to_have_count(1)
    assert displayed_count(page) < total
    pane = select(page, member)
    expect(pane).to_contain_text(member["email"])
    if member.get("licence_ffme"):
        expect(pane).to_contain_text(member["licence_ffme"])
    page.locator("#search-input").fill("")
    expect(page.locator(ROWS)).to_have_count(total)


def test_season_switch(page):
    open_members(page)
    current = displayed_count(page)
    seasons = page.locator("#season-select option")
    expect(seasons).to_have_count(2)
    page.locator("#season-select").select_option(index=1)
    previous = seasons.nth(1).get_attribute("value")
    expect(page.locator("#count-summary")).to_contain_text(f"(saison {previous})")
    assert displayed_count(page) != current, "the seed re-registers only part of the members"


def test_slot_filters(page):
    open_members(page)
    total = displayed_count(page)
    page.locator("#toggle-filter-box").click()
    expect(page.locator("#filter-box")).to_be_visible()
    page.locator("#cren-none").click()
    expect(page.locator("#members-tbody")).to_contain_text("Aucun adhérent ne correspond")
    page.locator("#cren-all").click()
    assert displayed_count(page) >= total

    slot = page.locator("#creneau-list label.opt").first
    in_slot = int(slot.locator(".n").inner_text())
    before = displayed_count(page)
    slot.locator("input").uncheck()
    expect(page.locator("#count-summary")).to_contain_text(f"{before - in_slot} adhérent")


def test_sort_by_last_name(page):
    open_members(page)
    names = lambda: [r.split("\t")[0] for r in page.locator(ROWS).all_inner_texts()]  # noqa: E731
    ascending = names()
    assert ascending == sorted(ascending, key=str.lower)
    page.locator("#members-table th[data-sort='last_name']").click()
    expect(page.locator(ROWS).first).to_contain_text(ascending[-1])


def test_csv_export(page, tmp_path):
    open_members(page)
    total = displayed_count(page)
    with page.expect_download() as info:
        page.locator("#export-csv-btn").click()
    target = tmp_path / info.value.suggested_filename
    info.value.save_as(target)
    rows = list(csv.reader(io.StringIO(target.read_text(encoding="utf-8-sig")), delimiter=";"))
    assert rows[0][:3] == ["Nom", "Prénom", "Date de naissance"]
    assert len(rows) == 1 + total
    # Spreadsheet formula injection neutralised (alj-core.js csvSafe): only phone/signed numbers
    # may start with + or -, nothing may start with = or @
    risky = [c for row in rows[1:] for c in row if c[:1] in ("=", "+", "-", "@")]
    assert all(re.fullmatch(r"[+-][\d\s().,]*", c) for c in risky), risky
    assert any(c.startswith("+") for c in risky), "seeded phone numbers are exported as is"


def test_edit_member(page, people):
    member = people[1]
    phone = "+44 20 " + str(uuid.uuid4().int)[:8]
    open_members(page)
    accept_dialogs(page)
    select(page, member).locator("#btn-action-edit").click()
    expect(page.locator("#member-edit-modal")).to_be_visible()
    page.locator("#edit-phone").fill(phone)
    page.locator("#edit-badge-rouge").select_option("Oui")
    page.locator("#edit-save-btn").click()
    expect(page.locator("#toast")).to_contain_text("mise à jour avec succès")
    expect(page.locator("#detail-pane")).to_contain_text(phone)

    # Saved on the server and replicated to Firestore: still there after a reload
    page.reload()
    expect(page.locator(ROWS).first).to_be_visible(timeout=20_000)
    pane = select(page, member)
    expect(pane).to_contain_text(phone, timeout=20_000)
    expect(pane.locator("tr").filter(has_text="Badge rouge")).to_contain_text("Oui")


def test_edit_without_change(page, people):
    open_members(page)
    select(page, people[0]).locator("#btn-action-edit").click()
    page.locator("#edit-save-btn").click()
    expect(page.locator("#toast")).to_contain_text("Aucune modification")
    expect(page.locator("#member-edit-modal")).to_be_hidden()


def test_send_email(page, mailpit, people):
    member = people[2]
    open_members(page)
    accept_dialogs(page)
    select(page, member).locator("#btn-action-email").click()
    expect(page.locator("#em-dest-email")).to_contain_text(member["email"])
    page.locator("#em-subject").fill("Practice moved, {first_name}")
    page.locator("#em-body").fill("Hello {first_name}, practice moves to Thursday.")
    expect(page.locator("#em-preview-box")).to_contain_text(f"Practice moved, {member['prenom']}")
    page.locator("#em-submit-btn").click()
    expect(page.locator("#toast")).to_contain_text("E-mail envoyé avec succès")

    [sent] = mailpit.wait_for(f"to:{member['email']}")
    assert sent["Subject"] == f"Practice moved, {member['prenom']}"
    assert f"Hello {member['prenom']}, practice moves to Thursday." in sent["Text"]


def test_email_needs_subject_and_body(page, people):
    open_members(page)
    accept_dialogs(page)
    select(page, people[0]).locator("#btn-action-email").click()
    page.locator("#em-submit-btn").click()
    expect(page.locator("#toast")).to_contain_text("renseigner le sujet et le message")
    expect(page.locator("#email-modal")).to_be_visible()


def test_payment_certificate(page, mailpit, people, tmp_path):
    member = people[3]
    open_members(page)
    accept_dialogs(page)
    select(page, member).locator("#btn-action-attestation").click()
    expect(page.locator("#attestation-modal")).to_be_visible()
    # The PDF is generated by the server (WeasyPrint), then shown in the preview frame
    expect(page.locator("#att-download-btn")).to_be_enabled(timeout=30_000)
    expect(page.locator("#att-pdf-frame")).to_be_visible()
    recipient = page.locator("#att-to-email").input_value()
    assert "@" in recipient

    with page.expect_download() as info:
        page.locator("#att-download-btn").click()
    pdf = tmp_path / info.value.suggested_filename
    info.value.save_as(pdf)
    assert re.match(r"Attestation_.+\.pdf$", pdf.name)
    assert pdf.read_bytes().startswith(b"%PDF") and pdf.stat().st_size > 1_000

    page.locator("#att-send-btn").click()
    expect(page.locator("#toast")).to_contain_text("Attestation envoyée avec succès")
    [sent] = mailpit.wait_for(f"to:{recipient}")
    attachments = sent["Attachments"]
    assert [a["ContentType"] for a in attachments] == ["application/pdf"]
    assert attachments[0]["FileName"].endswith(".pdf")
    expect(page.locator("#detail-pane")).to_contain_text("Attestation envoyée")


def test_coach_has_consultation_only(page, people):
    open_members(page, role="coach")
    pane = select(page, people[0])
    expect(pane).to_contain_text("Mode consultation coach")
    for action in ("#btn-action-email", "#btn-action-attestation", "#btn-action-edit"):
        expect(pane.locator(action)).to_have_count(0)
