"""PWA service worker (web/sw.js): precache, never-cached routes, pages served offline.

Service workers are blocked in the other tests (they cache the emulator hosts cache-first)."""
import pytest
from playwright.sync_api import expect

from helpers.data import eventually

pytestmark = pytest.mark.browser_context_args(service_workers="allow")

_CACHE_KEYS = "() => caches.keys()"
_CACHED_URLS = """async (name) => {
  const cache = await caches.open(name);
  return (await cache.keys()).map(r => new URL(r.url).pathname + new URL(r.url).search);
}"""


def _controlled(page, path="/bureau/"):
    """Loads the page until the service worker is installed and controls it."""
    page.goto(path)
    page.evaluate("() => navigator.serviceWorker.ready")
    if not page.evaluate("() => !!navigator.serviceWorker.controller"):
        page.reload()
    assert page.evaluate("() => !!navigator.serviceWorker.controller")
    return page


def test_cache_contents(page):
    """Precache named after the web version; the API and runtime config are never cached."""
    web_version = page.request.get("/api/web-version").json()["web_version"]
    _controlled(page)
    cache_name = f"alj-escalade-v{web_version}"
    assert page.evaluate(_CACHE_KEYS) == [cache_name], "old caches are deleted on activation"
    cached = page.evaluate(_CACHED_URLS, cache_name)
    for path in ("/bureau/", "/competitions", "/static-web/alj-core.js", "/static-web/alj-firebase.js"):
        assert path in cached, f"{path} not precached"

    page.evaluate("() => Promise.all([fetch('/api/web-version'), fetch('/runtime-config.js'), fetch('/health')])")

    def cached_as_fetched():
        cached = page.evaluate(_CACHED_URLS, cache_name)
        # Same-origin pages and assets are cached as they are fetched (network first, stored after answering)
        assert "/health" in cached
        assert "/api/web-version" not in cached
        assert "/runtime-config.js" not in cached
    eventually(cached_as_fetched)


def test_pages_open_offline(page, context):
    _controlled(page)
    expect(page.locator("#gate-login")).to_be_visible()
    context.set_offline(True)
    try:
        page.reload()
        # Shell rendered from the cache: menu and login gate, no browser error page
        expect(page.locator("nav a[data-page='adherents']")).to_be_visible()
        expect(page.locator("#gate")).to_be_visible()
        page.goto("/bureau/competitions")
        expect(page.locator("nav a[data-page='competitions']")).to_be_visible()
    finally:
        context.set_offline(False)
