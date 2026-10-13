"""Every page loads in dev mode (emulator banner, no JavaScript error) and the stack is wired."""
import re
import smtplib
from email.message import EmailMessage

import pytest
from playwright.sync_api import expect

from helpers import stack

pytestmark = pytest.mark.smoke

BUREAU_PAGES = ["/bureau/", "/bureau/adherents", "/bureau/communications", "/bureau/competitions", "/bureau/planning",
                "/bureau/outils", "/bureau/parametres"]
MOBILE_PAGES = ["/competitions", "/index"]


def test_health_and_versions(page):
    health = page.request.get("/health")
    assert health.ok and health.json()["status"] == "healthy"
    web_version = page.request.get("/api/web-version").json()["web_version"]
    assert web_version


def test_runtime_config_is_dev(page):
    page.goto("/bureau/")
    runtime = page.evaluate("() => window.ALJ_RUNTIME")
    assert runtime["env"] == "dev"
    assert runtime["projectId"] == "demo-alj"


@pytest.mark.parametrize("path", BUREAU_PAGES)
def test_bureau_page_loads(page, path):
    page.goto(path)
    expect(page.locator("#alj-dev-banner")).to_be_visible()
    expect(page.locator("#gate-login")).to_be_visible()


@pytest.mark.parametrize("path", MOBILE_PAGES)
def test_mobile_page_loads(mobile_page, path):
    mobile_page.goto(path)
    expect(mobile_page).to_have_url(re.compile(re.escape(path) + "$"))
    expect(mobile_page.locator("#alj-dev-banner")).to_be_visible()


def test_dev_smtp_reaches_mailpit(mailpit):
    """The server's SMTP settings (dev/dev.env, port of the e2e stack) deliver to Mailpit."""
    smtp = {**stack.read_env_file(stack.DEV_ENV_FILE), **stack.STACK_ENV}
    msg = EmailMessage()
    msg["From"] = smtp["SMTP_FROM_EMAIL"]
    msg["To"] = "harry.potter@hogwarts.example"
    msg["Subject"] = "e2e smtp check"
    msg.set_content("hello")
    with smtplib.SMTP(smtp["SMTP_HOST"], int(smtp["SMTP_PORT"]), timeout=10) as client:
        client.send_message(msg)
    [received] = mailpit.wait_for("subject:\"e2e smtp check\"")
    assert received["To"][0]["Address"] == "harry.potter@hogwarts.example"
