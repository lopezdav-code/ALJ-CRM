"""
Fixtures of the e2e suite (Playwright, pytest-playwright), run in parallel by pytest-xdist.

Session (helpers/session.py), started once by the xdist controller (or by the only process with -n 0)
before any test: the throwaway e2e stack (e2e/docker-compose.yml: Firebase emulator + Mailpit on their
own ports), seeded, the fake HelloAsso and the server in dev mode on E2E_PORT (default 8090). The
workers receive the server's URL and environment. The stack is removed at the end (E2E_KEEP_STACK=1
keeps it). The dev stack of dev/docker-compose.yml and its data are never touched.

Tests run concurrently against that one server: those that change state other tests read (fake
HelloAsso items, planning slots) share an xdist_group, which runs them one after another on one worker.

Every browser context blocks service workers: sw.js caches the emulator hosts cache-first, which
would leak state between tests.
"""
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext, expect

from helpers import data as test_data_helpers, helloasso
from helpers.auth import login_as as _login_as
from helpers.data import TestData
from helpers.mailpit import Mailpit
from helpers.session import E2ESession

DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
PHONE_DEVICE = "Pixel 7"
EXPECT_TIMEOUT = 5_000      # Playwright's default
KNOWN_BUG_TIMEOUT = 2_000   # see known_bug_timeouts

_SESSION = pytest.StashKey[E2ESession]()


def _is_worker(config) -> bool:
    return hasattr(config, "workerinput")


def pytest_sessionstart(session):
    """Controller only (xdist's own sessionstart, which starts the workers, runs last)."""
    config = session.config
    if _is_worker(config) or config.option.collectonly:
        return
    # Stack, seed and server logs, next to the Playwright artifacts (uploaded by the CI on failure).
    # Emptied here, once: see delete_output_dir
    logs_dir = Path(config.getoption("--output")).resolve()
    shutil.rmtree(logs_dir, ignore_errors=True)
    logs_dir.mkdir(parents=True)
    e2e = E2ESession(logs_dir)
    try:
        e2e.start()
    except (RuntimeError, TimeoutError, OSError) as e:
        e2e.stop(failed=False)
        pytest.exit(f"e2e session did not start: {e}\n(logs: {logs_dir})", returncode=3)
    config.stash[_SESSION] = e2e


@pytest.hookimpl(optionalhook=True)
def pytest_configure_node(node):
    """xdist: hands the server's URL and environment to each worker."""
    e2e = node.config.stash.get(_SESSION, None)
    if e2e is not None:
        node.workerinput["e2e"] = {"url": e2e.url, "env": e2e.env}


def pytest_sessionfinish(session):
    e2e = session.config.stash.get(_SESSION, None)
    if e2e is not None:
        e2e.stop(failed=session.testsfailed > 0)


@pytest.fixture(scope="session", autouse=True)
def delete_output_dir():
    """Replaces pytest-playwright's: it empties --output at the first test, which would delete the session's
    logs, and would run on every xdist worker. pytest_sessionstart empties it instead."""


@dataclass(frozen=True)
class Server:
    url: str
    env: dict


@pytest.fixture(scope="session")
def server(pytestconfig) -> Server:
    """The session's server (URL, environment of the dev subprocesses)."""
    if _is_worker(pytestconfig):
        return Server(**pytestconfig.workerinput["e2e"])
    e2e = pytestconfig.stash[_SESSION]
    return Server(e2e.url, e2e.env)


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
def mailpit() -> Mailpit:
    """Shared by the workers and cleared once per run only: search a test's own e-mails by recipient and
    subject (unique_name)."""
    return Mailpit()


@pytest.fixture(scope="session")
def test_data(server) -> TestData:
    """Creates and reads competitions through the application's repository (helpers/data.py)."""
    data = TestData(server.env)
    yield data
    data.close()


@pytest.fixture
def fake_helloasso() -> helloasso.FakeHelloAsso:
    """Empty fake HelloAsso: each test loads the forms and items it needs (fake.set(items)). One state for
    the whole server: its tests share the « helloasso » xdist_group."""
    fake = helloasso.FakeHelloAsso()
    fake.clear()
    return fake
