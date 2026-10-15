"""Desktop / smartphone choice of the PWA entry pages (web/shared/alj-vue.js)."""
import re

import pytest
from playwright.sync_api import expect

BUREAU = re.compile(r"/bureau/$")


@pytest.mark.parametrize("path", ["/", "/competitions", "/index"])
def test_desktop_goes_to_office(page, path):
    page.goto(path)
    expect(page).to_have_url(BUREAU)


def test_vue_mobile_is_remembered(page):
    page.goto("/competitions?vue=mobile")
    expect(page).to_have_url(re.compile(r"/competitions\?vue=mobile$"))
    page.goto("/competitions")
    expect(page).to_have_url(re.compile(r"/competitions$"))


def test_desktop_link_forgets_mobile_choice(page):
    page.goto("/competitions?vue=mobile")
    page.locator("header a[href='/bureau/']").click()
    expect(page).to_have_url(BUREAU)
    page.goto("/competitions")
    expect(page).to_have_url(BUREAU)


def test_vue_pwa_is_one_off(page):
    page.goto("/competitions?vue=pwa")
    expect(page).to_have_url(re.compile(r"/competitions\?vue=pwa$"))
    page.goto("/competitions")
    expect(page).to_have_url(BUREAU)


def test_phone_stays_on_pwa(mobile_page):
    mobile_page.goto("/competitions")
    expect(mobile_page).to_have_url(re.compile(r"/competitions$"))
    expect(mobile_page.locator("header a[href='/bureau/']")).to_have_count(0)
