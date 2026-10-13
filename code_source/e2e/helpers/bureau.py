"""Office portal competitions page (web/bureau/competitions.html): navigation and locators."""
from playwright.sync_api import Locator, Page, expect

from helpers.auth import login_as
from helpers.mobile import SEEDED_COMPETITION


def open_competitions(page: Page, role: str = "admin") -> Page:
    page.goto("/bureau/competitions")
    login_as(page, role)
    expect(competition_card(page, SEEDED_COMPETITION)).to_be_visible()
    return page


def go_to(page: Page, section: str) -> None:
    """Main tabs: comps, helloasso, bilan, coachs."""
    page.locator(f"#btn-nav-{section}").click()


def competition_card(page: Page, nom: str) -> Locator:
    return page.locator("#comps-list-container .comp-card").filter(
        has=page.locator(".comp-card-title").get_by_text(nom, exact=True))


def select_competition(page: Page, nom: str) -> Locator:
    """Opens the competition's workspace (right pane)."""
    competition_card(page, nom).click()
    workspace = page.locator("#comp-workspace")
    expect(workspace).to_contain_text(nom)
    return workspace


def participant_row(page: Page, member: dict) -> Locator:
    return page.locator("#parts-tbody tr[data-aid]").filter(has_text=member["prenom"]).filter(
        has_text=member["nom"].upper())


def coach_card(page: Page, nom: str) -> Locator:
    return page.locator("#coachs-list-container .comp-card").filter(has_text=nom)
