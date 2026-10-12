"""
Fixtures of the e2e suite (Playwright, pytest-playwright).

Session: check the dev stack (docker compose), seed the emulator, start the server in dev mode
on E2E_PORT (default 8090). Every browser context blocks service workers: sw.js caches the
emulator hosts (localhost:9099/8081) cache-first, which would leak state between tests.

Running the suite RESETS the local emulator data (same as dev/seed/seed_emulator.py).
"""
import os
from pathlib import Path

import pytest
from playwright.sync_api import BrowserContext

from helpers import stack
from helpers.auth import login_as as _login_as
from helpers.mailpit import Mailpit

DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
PHONE_DEVICE = "Pixel 7"


@pytest.fixture(scope="session")
def dev_stack():
    missing = stack.missing_services()
    if missing:
        pytest.fail(f"dev stack not running ({', '.join(missing)}). From code_source/, run: "
                    "docker compose -f dev/docker-compose.yml up -d", pytrace=False)


@pytest.fixture(scope="session")
def e2e_logs(pytestconfig) -> Path:
    """Seed and server logs, next to the Playwright artifacts (uploaded by the CI on failure)."""
    folder = Path(pytestconfig.getoption("--output")).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@pytest.fixture(scope="session")
def server(dev_stack, e2e_logs, tmp_path_factory, request):
    data_dir = tmp_path_factory.mktemp("alj-data")
    env = stack.dev_environment(data_dir)
    log_path = e2e_logs / "server.log"
    stack.seed(env, log_path)
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


def _checked_page(context: BrowserContext):
    """New page whose uncaught JavaScript exceptions fail the test (reported at teardown)."""
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    assert not errors, f"uncaught JavaScript error(s): {errors}"


@pytest.fixture
def page(context):
    yield from _checked_page(context)


@pytest.fixture
def mobile_page(mobile_context):
    yield from _checked_page(mobile_context)


@pytest.fixture
def login_as():
    """login_as(page, "admin" | "coach" | "readonly" | "stranger") → Account."""
    return _login_as


@pytest.fixture
def mailpit(dev_stack) -> Mailpit:
    client = Mailpit()
    client.clear()
    return client
