"""Mobile competitions page (web/competitions.html): navigation and locators."""
from playwright.sync_api import Locator, Page, expect

from helpers.auth import login_as

# Always present after the seed: proves the competitions have been loaded
SEEDED_COMPETITION = "Hogwarts Lead Open"


def open_app(page: Page, role: str = "coach") -> Page:
    page.goto("/competitions")
    login_as(page, role)
    expect(competition_card(page, SEEDED_COMPETITION)).to_be_visible()
    return page


def go_to(page: Page, name: str) -> None:
    """Bottom navigation: comps, participants, helloasso, coaches, balance."""
    page.locator(f"nav button[data-page='{name}']").click()
    expect(page.locator(f"#page-{name}")).to_have_class("page active")


def competition_card(page: Page, nom: str, archived: bool = False) -> Locator:
    container = "#comps-archived-list" if archived else "#comps-list"
    return page.locator(f"{container} > .card").filter(has=page.locator(".m-name").get_by_text(nom, exact=True))


def open_participants(page: Page, nom: str) -> None:
    competition_card(page, nom).get_by_role("button", name="Voir détail").click()
    expect(page.locator("#page-participants")).to_have_class("page active")


def participant_card(page: Page, member: dict) -> Locator:
    return page.locator("#p-list .card").filter(
        has=page.locator(".m-name").get_by_text(f"{member['nom']} {member['prenom']}", exact=True))


def toast(page: Page) -> Locator:
    return page.locator("#toast")


def accept_dialogs(page: Page) -> None:
    """confirm() boxes (delete, archive…) are dismissed by Playwright unless accepted."""
    page.on("dialog", lambda dialog: dialog.accept())
