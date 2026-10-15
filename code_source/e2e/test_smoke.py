"""Every page loads in dev mode (emulator banner, no JavaScript error)."""
import re

import pytest
from playwright.sync_api import expect

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

