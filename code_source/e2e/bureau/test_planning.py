"""Office portal, planning page: week view, table and filters, slot create/edit/delete, Excel exports."""
import io

import openpyxl
import pytest
from playwright.sync_api import expect

from helpers.auth import login_as
from helpers.data import unique_name
from helpers.mobile import accept_dialogs

ROWS = "#planning-table-tbody tr"


@pytest.fixture
def planning(page):
    """Seeded slots (from the API) and cleanup of the slots a test creates: other tests read the planning."""
    before = {s["id"] for s in page.request.get("/api/planning").json()}
    yield page.request.get("/api/planning").json()
    for slot in page.request.get("/api/planning").json():
        if slot["id"] not in before:
            page.request.delete(f"/api/planning/item/{slot['id']}")


def _open(page, role="admin"):
    page.goto("/bureau/planning")
    login_as(page, role)
    expect(page.locator("#active-slots-count")).to_contain_text("créneau(x) configuré(s)")
    return page


def _row(page, groupe):
    return page.locator(ROWS).filter(has=page.get_by_text(groupe, exact=True))


def _xlsx_text(download, folder) -> str:
    target = folder / download.suggested_filename
    download.save_as(target)
    book = openpyxl.load_workbook(io.BytesIO(target.read_bytes()))
    return " ".join(str(c) for ws in book.worksheets for row in ws.iter_rows(values_only=True) for c in row if c)


def test_week_view_and_table(page, planning):
    _open(page)
    expect(page.locator("#active-slots-count")).to_have_text(f"{len(planning)} créneau(x) configuré(s)")
    # One card per slot of a single day (the « Lundi / Jeudi » slot spans two days: not on the grid)
    on_grid = [s for s in planning if s["jour"] in ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")]
    expect(page.locator(".plan-slot-card")).to_have_count(len(on_grid))
    saturday = next(s for s in planning if s["jour"] == "Samedi")
    expect(page.locator(".day-column[data-day='Samedi'] .plan-slot-card")).to_contain_text(saturday["groupe"])

    page.locator("#tab-btn-table").click()
    expect(page.locator(ROWS)).to_have_count(len(planning))
    page.locator("#planning-search-input").fill("bouldering")
    expect(page.locator(ROWS)).to_have_count(1)
    page.locator("#planning-search-input").fill("")
    page.locator(".filter-type-chip[data-type='compétition']").click()
    competition = [s for s in planning if s["type"] == "compétition"]
    expect(page.locator(ROWS)).to_have_count(len(competition))


def test_create_edit_delete_slot(page, planning):
    groupe = unique_name("E2E Slot")
    _open(page)
    accept_dialogs(page)
    page.locator("#btn-create-slot").click()
    expect(page.locator("#slot-modal")).to_be_visible()
    page.locator("#slot-groupe").fill(groupe)
    page.locator("#slot-jour").select_option("Samedi")
    page.locator("#slot-horaires").fill("14:00 - 16:00")
    page.locator("#slot-type").select_option("perfectionnement")
    page.locator("#slot-encadrants").fill("Remus Lupin, Rubeus Hagrid")
    page.locator("#slot-tarifs-checkboxes label").filter(has_text="Independent bouldering").locator("input").check()
    page.locator("#btn-save-modal").click()
    expect(page.locator("#toast")).to_contain_text(f"Créneau « {groupe} » enregistré")
    expect(page.locator(".day-column[data-day='Samedi'] .plan-slot-card").filter(has_text=groupe)).to_be_visible()

    page.locator("#tab-btn-table").click()
    row = _row(page, groupe)
    expect(row).to_contain_text("Remus Lupin, Rubeus Hagrid")
    expect(row).to_contain_text("Independent bouldering")
    stored = next(s for s in page.request.get("/api/planning").json() if s["groupe"] == groupe)
    assert (stored["jour"], stored["horaires"], stored["type"]) == ("Samedi", "14:00 - 16:00", "perfectionnement")

    row.locator(".btn-edit-slot").click()
    expect(page.locator("#slot-groupe")).to_have_value(groupe)
    page.locator("#slot-horaires").fill("16:00 - 18:00")
    page.locator("#btn-save-modal").click()
    expect(page.locator("#toast")).to_contain_text("enregistré")
    page.locator("#tab-btn-table").click()
    expect(_row(page, groupe)).to_contain_text("16:00 - 18:00")

    _row(page, groupe).locator(".btn-del-slot").click()
    expect(page.locator("#toast")).to_contain_text("Créneau supprimé")
    expect(_row(page, groupe)).to_have_count(0)
    assert all(s["groupe"] != groupe for s in page.request.get("/api/planning").json())


@pytest.mark.xfail(strict=True, reason="the week view has no Sunday column (daysList stops at Samedi) "
                                       "although the slot form offers « Dimanche »")
def test_sunday_slot_on_week_view(page, planning):
    groupe = unique_name("E2E Sunday")
    _open(page)
    page.locator("#btn-create-slot").click()
    page.locator("#slot-groupe").fill(groupe)
    page.locator("#slot-jour").select_option("Dimanche")
    page.locator("#slot-horaires").fill("10:00 - 12:00")
    page.locator("#btn-save-modal").click()
    expect(page.locator("#toast")).to_contain_text("enregistré")
    expect(page.locator(".plan-slot-card").filter(has_text=groupe)).to_be_visible(timeout=3_000)


def test_name_and_hours_are_required(page, planning):
    _open(page)
    page.locator("#btn-create-slot").click()
    page.locator("#slot-horaires").fill("")
    page.locator("#btn-save-modal").click()
    # Browser validation of the form (required fields): nothing is sent
    expect(page.locator("#slot-modal")).to_be_visible()
    assert len(page.request.get("/api/planning").json()) == len(planning)


def test_excel_exports(page, planning, tmp_path):
    _open(page)
    for button, title in (("#btn-export-excel-grid", "Saison"), ("#btn-export-excel-list", "Groupe")):
        page.locator("#btn-export-menu").click()
        with page.expect_download() as info:
            page.locator(button).click()
        assert info.value.suggested_filename.endswith(".xlsx")
        text = _xlsx_text(info.value, tmp_path)
        assert title in text
        assert all(slot["groupe"] in text for slot in planning), f"{button}: a slot is missing"
