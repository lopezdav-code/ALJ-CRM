"""Office portal, Outils page: members map, pivot table, attendance sheets, FFME export; Google token
warning of every office page."""
import csv
import io
import json
import zipfile

import openpyxl
import pytest

from playwright.sync_api import expect

from helpers.auth import login_as


def _open(page, role="admin"):
    page.goto("/bureau/outils")
    login_as(page, role)
    return page


def test_members_map(page):
    """Map of the members' addresses (Leaflet). The e2e setup pre-fills the geocache, so the
    server never calls Nominatim."""
    _open(page)
    expect(page.locator("#iframe-map")).to_be_visible(timeout=30_000)
    frame = page.frame_locator("#iframe-map")
    expect(frame.locator(".leaflet-container")).to_be_visible()
    # Members are shown as markers grouped in clusters
    clusters = frame.locator(".marker-cluster, .leaflet-marker-icon")
    expect(clusters.first).to_be_visible(timeout=15_000)
    assert "nominatim" not in page.request.get("/map").text().lower()

    page.locator("#tools-refresh-btn").click()
    expect(page.locator("#toast")).to_contain_text("Carte réactualisée")


def test_pivot_table_by_season(page):
    _open(page)
    page.locator("#tab-btn-pivot").click()
    expect(page.locator("#iframe-pivot")).to_be_visible(timeout=30_000)
    seasons = page.locator("#pivot-season-select option")
    expect(seasons).to_have_count(3)  # all seasons + the two seeded ones
    frame = page.frame_locator("#iframe-pivot")
    expect(frame.locator(".pvtTable, .pvtUi").first).to_be_visible(timeout=15_000)

    with page.expect_response(lambda r: "/pivot?season=2025-2026" in r.url and r.ok):
        page.locator("#pivot-season-select").select_option("2025-2026")
    expect(page.locator("#iframe-pivot")).to_be_visible()
    expect(frame.locator(".pvtTable, .pvtUi").first).to_be_visible()


def test_expired_google_token_warning(page):
    """Every office page warns when the club's Google token has expired (alj-shell.js)."""
    page.route("**/api/auth/google/status", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"status": "expired", "user_email": "office@hogwarts.example"})))
    page.goto("/bureau/")
    login_as(page, "admin")
    expect(page.locator("#google-auth-warning")).to_be_visible()


# ---------------------------------------------------------------------------
# Attendance sheets and FFME licences export
# ---------------------------------------------------------------------------
def _open_tab(page, tab):
    _open(page)
    page.locator(f"#tab-btn-{tab}").click()
    expect(page.locator(f"#pane-{tab}")).to_be_visible()
    return page


def _saved(download, folder):
    target = folder / download.suggested_filename
    download.save_as(target)
    return target


def test_course_attendance_sheets(page, tmp_path):
    config = page.request.get("/api/presence/config").json()
    courses = config["cours"]
    assert courses, "the seed plans supervised courses"
    _open_tab(page, "presence")
    expect(page.locator("#cours-badge-count")).to_have_text(f"{len(courses)} créneau(x)")
    expect(page.locator(".cours-cb")).to_have_count(len(courses))
    expect(page.locator("#cours-start-date")).to_have_value(config["default_dates"]["start"])

    page.locator("#btn-deselect-all-cours").click()
    page.locator("#btn-download-cours").click()
    expect(page.locator("#toast")).to_contain_text("cocher au moins un groupe")

    # One workbook, one sheet page per course
    page.locator("#btn-select-all-cours").click()
    with page.expect_download() as info:
        page.locator("#btn-download-cours").click()
    workbook = openpyxl.load_workbook(_saved(info.value, tmp_path))
    text = " ".join(str(c) for ws in workbook.worksheets for row in ws.iter_rows(values_only=True) for c in row if c)
    assert all(course["groupe"] in text for course in courses)

    # One file per course, in a ZIP archive
    page.locator("input[name='cours-format'][value='zip']").check()
    with page.expect_download() as info:
        page.locator("#btn-download-cours").click()
    with zipfile.ZipFile(_saved(info.value, tmp_path)) as archive:
        names = archive.namelist()
    assert len(names) == len(courses) and all(n.endswith(".xlsx") for n in names)


@pytest.mark.xfail(strict=True, reason="domain.planning_groups.is_autonome_creneau ignores the slot type "
                                       "(`autonome`) and only looks for « autonome » in the group/tariff names; "
                                       "the seeded names are English (« Independent »)")
def test_autonomous_attendance_sheet(page, tmp_path):
    _open_tab(page, "presence")
    expect(page.locator("#presence-autonome-summary")).not_to_contain_text("Total adhérents : 0")
    with page.expect_download() as info:
        page.locator("#btn-download-autonome").click()
    assert _saved(info.value, tmp_path).stat().st_size > 0


def test_ffme_licences_export(page, tmp_path):
    stats = page.request.get("/api/ffme/stats").json()
    _open_tab(page, "ffme")
    expect(page.locator("#ffme-stat-total")).to_have_text(str(stats["estimated_total"]))
    expect(page.locator("#ffme-stat-renewals")).to_have_text(str(stats["renewals_count"]))
    expect(page.locator("#ffme-stat-new")).to_have_text(str(stats["new_licences_count"]))
    assert stats["renewals_count"] + stats["new_licences_count"] == stats["estimated_total"]

    with page.expect_download() as info:
        page.locator("#btn-download-ffme").click()
    assert info.value.suggested_filename.startswith("import_ffme_")
    text = _saved(info.value, tmp_path).read_text(encoding="utf-8-sig")
    rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert rows[0][:3] == ["numero de licence", "nom", "prenom"]
    assert len([r for r in rows[1:] if r]) == stats["estimated_total"]

    page.locator("#ffme-include-termine").check()
    with page.expect_response(lambda r: "include_termine=true" in r.url and r.ok), page.expect_download():
        page.locator("#btn-download-ffme").click()
