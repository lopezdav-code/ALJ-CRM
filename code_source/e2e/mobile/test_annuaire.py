"""Mobile members directory (web/index.html): search, emergency contacts, filters, roles."""
import re

import pytest
from playwright.sync_api import expect

from helpers.auth import login_as

CARDS = "#members-list .card.member"


def _open(page, role="coach"):
    page.goto("/index")
    login_as(page, role)
    return page


def _shown(page) -> int:
    return int(page.locator("#kpi-shown").inner_text())


@pytest.fixture(scope="module")
def member(test_data):
    """A seeded member with a phone number (some seeded records are deliberately incomplete)."""
    return next(m for m in sorted(test_data.members(), key=lambda m: m["nom"]) if m.get("phone"))


def test_search_and_member_card(mobile_page, member):
    page = _open(mobile_page)
    expect(page.locator(CARDS).first).to_be_visible(timeout=20_000)
    total = _shown(page)
    assert total > 20
    page.locator("#search").fill(member["nom"].lower())
    card = page.locator(CARDS).filter(has_text=f"{member['prenom']} {member['nom']}")
    expect(card).to_have_count(1)
    assert _shown(page) < total

    expect(card.locator(".m-detail")).to_be_hidden()
    card.click()
    expect(card.locator(".m-detail")).to_be_visible()
    expect(card).to_contain_text(member["email"])
    expect(card.get_by_role("link", name="Appeler")).to_have_attribute("href", re.compile(r"^tel:\+?\d+$"))


def test_emergency_contacts(mobile_page, member):
    page = _open(mobile_page)
    page.locator("nav button[data-page='urgency']").click()
    expect(page.locator("#urgency-count")).to_contain_text("au moins 2 lettres")
    page.locator("#urgency-search").fill(member["nom"])
    card = page.locator("#urgency-list .card").filter(has_text=f"{member['prenom']} {member['nom']}")
    expect(card).to_have_count(1)
    expect(card).to_contain_text("Urgence 1")
    expect(card.get_by_role("link", name="Appeler").first).to_have_attribute("href", re.compile(r"^tel:"))


def test_season_and_slot_filters(mobile_page):
    page = _open(mobile_page)
    expect(page.locator(CARDS).first).to_be_visible(timeout=20_000)
    total = _shown(page)
    page.locator("nav button[data-page='filters']").click()
    page.locator("#cren-none").click()
    expect(page.locator("#kpi-shown")).to_have_text("0")
    page.locator("#cren-all").click()
    assert _shown(page) >= total

    page.locator("#season-select").select_option(index=1)
    expect(page.locator("#count-line")).to_contain_text("saison 2025-2026")
    assert _shown(page) != total


@pytest.mark.parametrize("role", ["readonly", "stranger"])
def test_reserved_to_coaches(mobile_page, role):
    page = _open(mobile_page, role)
    expect(page.locator("#setup-unauthorized")).to_be_visible()
    expect(page.locator("nav")).to_be_hidden()
    expect(page.locator(CARDS)).to_have_count(0)
