"""Office portal members page (web/bureau/adherents.html): navigation and locators."""
import re

from playwright.sync_api import Locator, Page, expect

from helpers.auth import login_as

ROWS = "#members-tbody tr[data-id]"


def open_members(page: Page, role: str = "admin") -> Page:
    page.goto("/bureau/adherents")
    login_as(page, role)
    expect(page.locator(ROWS).first).to_be_visible(timeout=20_000)
    return page


def displayed_count(page: Page) -> int:
    """« N adhérents affichés sur M (saison …) » → N."""
    return int(re.match(r"\d+", page.locator("#count-summary").inner_text()).group())


def find(page: Page, member: dict) -> Locator:
    """Searches the member (by last name) and returns their row."""
    page.locator("#search-input").fill(member["nom"])
    return page.locator(ROWS).filter(has_text=member["prenom"]).filter(has_text=member["nom"].upper())


def select(page: Page, member: dict) -> Locator:
    """Opens the member's detail pane."""
    find(page, member).click()
    pane = page.locator("#detail-pane")
    expect(pane.locator(".detail-name")).to_have_text(f"{member['prenom']} {member['nom'].upper()}")
    return pane
