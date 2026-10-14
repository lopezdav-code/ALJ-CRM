"""Office portal, communications page: e-mail templates (create, edit, delete), variables, WhatsApp text."""
import pytest
from playwright.sync_api import expect

from helpers.auth import login_as
from helpers.data import unique_name


def _open(page, role="admin"):
    page.goto("/bureau/communications")
    login_as(page, role)
    expect(page.locator("#template-select option").first).to_be_attached(timeout=20_000)
    return page


def _create(page, name):
    page.locator("#btn-new-tpl").click()
    page.locator("#new-template-name").fill(name)
    page.locator("#new-modal-confirm").click()
    expect(page.locator("#toast")).to_contain_text(f"Nouveau modèle « {name} » créé")
    expect(page.locator("#template-select")).to_have_value(name)


@pytest.fixture
def accept_with(page):
    """Accepts confirm() boxes and answers prompt() boxes with the given text."""
    answer = {"text": ""}
    page.on("dialog", lambda dialog: dialog.accept(answer["text"]) if dialog.type == "prompt" else dialog.accept())
    return answer


def test_template_lifecycle(page, accept_with):
    """Create, edit (kept after a reload), rename, delete."""
    _open(page)
    name = unique_name("E2E Template")
    _create(page, name)
    expect(page.locator("#subject-input")).to_have_value("Sujet du courriel")

    page.locator("#subject-input").fill("Training camp for {first_name}")
    page.locator("#body-input").fill("Hello {first_name}, see you at the camp.")
    page.locator("#sender-email").fill("competitions@alj-escalade.fr")
    page.locator("#btn-save-tpl").click()
    expect(page.locator("#toast")).to_contain_text(f"Modèle « {name} » enregistré")

    page.reload()
    _open(page)
    page.locator("#template-select").select_option(name)
    expect(page.locator("#subject-input")).to_have_value("Training camp for {first_name}")
    expect(page.locator("#body-input")).to_have_value("Hello {first_name}, see you at the camp.")
    expect(page.locator("#sender-email")).to_have_value("competitions@alj-escalade.fr")

    renamed = unique_name("E2E Renamed")
    page.locator("#template-name-input").fill(renamed)
    page.locator("#btn-save-tpl").click()
    expect(page.locator("#template-select")).to_have_value(renamed)
    expect(page.locator("#template-select option").filter(has_text=name)).to_have_count(0)

    page.locator("#btn-del-tpl").click()
    expect(page.locator("#toast")).to_contain_text(f"Modèle « {renamed} » supprimé")
    expect(page.locator("#template-select option").filter(has_text=renamed)).to_have_count(0)


def test_duplicate_name_refused(page, accept_with):
    _open(page)
    existing = page.locator("#template-select").input_value()
    page.locator("#btn-new-tpl").click()
    page.locator("#new-template-name").fill(existing.upper())
    page.locator("#new-modal-confirm").click()
    expect(page.locator("#toast")).to_contain_text("existe déjà")


def test_subject_and_sender_are_required(page, accept_with):
    _open(page)
    _create(page, unique_name("E2E Template"))
    page.locator("#subject-input").fill("")
    page.locator("#btn-save-tpl").click()
    expect(page.locator("#toast")).to_contain_text("sujet et le corps du message sont obligatoires")
    page.locator("#subject-input").fill("Subject")
    page.locator("#sender-email").fill("not-an-address")
    page.locator("#btn-save-tpl").click()
    expect(page.locator("#toast")).to_contain_text("adresse e-mail valide")


def test_variables_formatting_and_preview(page, accept_with):
    _open(page)
    _create(page, unique_name("E2E Template"))
    body = page.locator("#body-input")
    body.fill("")
    page.locator("#btn-toggle-vars").click()
    page.locator("#vars-panel .tag-btn[data-var='{first_name}']").click()
    expect(body).to_have_value("{first_name}")
    # Live preview renders the variables with the demo member
    expect(page.locator("#pv-body")).to_have_text("Alex")

    body.fill("")
    page.locator(".fmt-btn[data-wrap='b']").click()
    expect(body).to_have_value("<b>texte</b>")
    body.fill("")
    accept_with["text"] = "https://www.alj-escalade.fr"
    page.locator("#btn-wrap-link").click()
    expect(body).to_have_value('<a href="https://www.alj-escalade.fr">texte</a>')

    page.locator("#signature-checkbox").uncheck()
    expect(page.locator("#pv-signature")).to_be_hidden()


def test_whatsapp_text(page):
    _open(page)
    text = unique_name("Join the WhatsApp group of your slot:")
    page.locator("#whatsapp-input").fill(text)
    page.locator("#btn-save-whatsapp").click()
    expect(page.locator("#toast")).to_contain_text("Texte WhatsApp enregistré")
    page.reload()
    _open(page)
    expect(page.locator("#whatsapp-input")).to_have_value(text)


def test_coach_reads_only(page):
    _open(page, role="coach")
    for field in ("#subject-input", "#body-input", "#sender-email", "#whatsapp-input"):
        expect(page.locator(field)).to_be_disabled()
    for button in ("#btn-save-tpl", "#btn-new-tpl", "#btn-del-tpl", "#btn-save-whatsapp"):
        expect(page.locator(button)).to_have_count(0)
