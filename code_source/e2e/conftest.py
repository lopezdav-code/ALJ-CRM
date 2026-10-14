"""
Fixtures of the e2e suite (Playwright, pytest-playwright).

Session: start the throwaway e2e stack (e2e/docker-compose.yml: Firebase emulator + Mailpit on
their own ports), seed it, start the fake HelloAsso and the server in dev mode on E2E_PORT
(default 8090); the stack is removed at the end (E2E_KEEP_STACK=1 keeps it). The dev stack of
dev/docker-compose.yml and its data are never touched.

Every browser context blocks service workers: sw.js caches the emulator hosts cache-first, which
would leak state between tests.
"""
import os
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from helpers import data as test_data_helpers, helloasso, stack
from helpers.auth import login_as as _login_as
from helpers.data import TestData
from helpers.mailpit import Mailpit

DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
PHONE_DEVICE = "Pixel 7"
EXPECT_TIMEOUT = 5_000      # Playwright's default
KNOWN_BUG_TIMEOUT = 2_000   # see known_bug_timeouts


@pytest.fixture(scope="session")
def e2e_logs(pytestconfig) -> Path:
    """Stack, seed and server logs, next to the Playwright artifacts (uploaded by the CI on failure)."""
    folder = Path(pytestconfig.getoption("--output")).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@pytest.fixture(scope="session")
def e2e_stack(e2e_logs):
    """Fresh emulator + Mailpit for the run: the emulator's memory grows with use, and a run
    must not reset the developer's dev data."""
    log_path = e2e_logs / "stack.log"
    try:
        stack.start_stack(log_path)
    except (RuntimeError, TimeoutError, OSError) as e:
        pytest.fail(f"e2e stack (e2e/docker-compose.yml) did not start: {e}", pytrace=False)
    yield
    if os.environ.get("E2E_KEEP_STACK") != "1":
        stack.stop_stack(log_path)


@pytest.fixture(scope="session")
def fake_helloasso_server(e2e_logs, tmp_path_factory):
    """Fake HelloAsso API (e2e/fakes/helloasso_fake.py), reached by the server in dev mode only."""
    env = stack.dev_environment(tmp_path_factory.mktemp("fake-helloasso"))
    srv = stack.ServerProcess(env, helloasso.FAKE_PORT, e2e_logs / "fake-helloasso.log", app="helloasso_fake:app",
                              app_dir="e2e/fakes", health_path="/docs", check_env=False)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="session")
def server(e2e_stack, fake_helloasso_server, e2e_logs, tmp_path_factory, request):
    data_dir = tmp_path_factory.mktemp("alj-data")
    env = stack.dev_environment(data_dir, **helloasso.SERVER_ENV)
    log_path = e2e_logs / "server.log"
    stack.seed(env, log_path)
    data = TestData(env)
    try:
        data.save_setting("HELLOASSO_ANNUAL_CAMPAIGN", f"Event:{helloasso.COMPETITION_FORM}")
        data.fill_geocache()
    finally:
        data.close()   # before the server starts: fill_geocache used its SQLite file
    srv = stack.ServerProcess(env, int(os.environ.get("E2E_PORT", "8090")), log_path)
    srv.start()
    yield srv
    srv.stop()
    if request.session.testsfailed:
        print(f"\n--- server log (tail, full log: {log_path}) ---\n{stack.tail(log_path)}")


@pytest.fixture(scope="session")
def base_url(server) -> str:
    return server.url


@pytest.fixture(scope="session")
def connect_options():
    """E2E_PLAYWRIGHT_WS=ws://127.0.0.1:3000/ : browser served by the official Playwright image
    (no system libraries needed on the host, see dev/README.md)."""
    ws_endpoint = os.environ.get("E2E_PLAYWRIGHT_WS")
    return {"endpoint": ws_endpoint} if ws_endpoint else None


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "service_workers": "block", "locale": "fr-FR"}


@pytest.fixture
def context(new_context) -> BrowserContext:
    """Desktop context: ≥ 1024 px with a mouse, so the PWA pages redirect to /bureau/."""
    return new_context(viewport=DESKTOP_VIEWPORT)


@pytest.fixture
def mobile_context(new_context, playwright) -> BrowserContext:
    device = {k: v for k, v in playwright.devices[PHONE_DEVICE].items() if k != "default_browser_type"}
    return new_context(**device)


# Raised by Playwright itself, not by the pages: service_workers="block" patches navigator.serviceWorker
# in every frame, which throws in the sandboxed iframes of the Outils page (map, pivot table)
_HARNESS_ERRORS = ("Failed to read the 'serviceWorker' property from 'Navigator': Service worker is disabled "
                   "because the context is sandboxed",)


def _checked_page(context: BrowserContext):
    """New page whose uncaught JavaScript exceptions fail the test (reported at teardown)."""
    page = context.new_page()
    errors = []

    def record(error):
        if not str(error).startswith(_HARNESS_ERRORS):
            errors.append(str(error))
    page.on("pageerror", record)
    yield page
    assert not errors, f"uncaught JavaScript error(s): {errors}"


@pytest.fixture
def page(context):
    yield from _checked_page(context)


@pytest.fixture
def mobile_page(mobile_context):
    yield from _checked_page(mobile_context)


@pytest.fixture(autouse=True)
def known_bug_timeouts(request):
    """xfail tests fail by timing out at the bug: they wait 2 s instead of the 5 s (expect, eventually) /
    30 s (actions) defaults. Explicit timeouts (HelloAsso sync…) still apply. A step must stay under
    2 s for the XPASS to show once the bug is fixed."""
    if request.node.get_closest_marker("xfail") is None:
        yield
        return
    for name in ("page", "mobile_page"):
        if name in request.fixturenames:
            request.getfixturevalue(name).set_default_timeout(KNOWN_BUG_TIMEOUT)
    expect.set_options(timeout=KNOWN_BUG_TIMEOUT)
    test_data_helpers.EVENTUALLY_TIMEOUT = KNOWN_BUG_TIMEOUT / 1000
    yield
    expect.set_options(timeout=EXPECT_TIMEOUT)
    test_data_helpers.EVENTUALLY_TIMEOUT = EXPECT_TIMEOUT / 1000


@pytest.fixture
def login_as():
    """login_as(page, "admin" | "coach" | "readonly" | "stranger") → Account."""
    return _login_as


@pytest.fixture
def mailpit(e2e_stack) -> Mailpit:
    client = Mailpit()
    client.clear()
    return client


@pytest.fixture(scope="session")
def test_data(server) -> TestData:
    """Creates and reads competitions through the application's repository (helpers/data.py)."""
    data = TestData(server.env)
    yield data
    data.close()


@pytest.fixture
def fake_helloasso(fake_helloasso_server) -> helloasso.FakeHelloAsso:
    """Empty fake HelloAsso: each test loads the forms and items it needs (fake.set(items))."""
    fake = helloasso.FakeHelloAsso()
    fake.clear()
    return fake
