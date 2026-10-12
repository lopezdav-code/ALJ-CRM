"""
Mailpit REST client: the dev SMTP (dev/dev.env) delivers every e-mail to Mailpit, which never
relays them. API reference: https://mailpit.axllent.org/docs/api-v1/
"""
import json
import time
import urllib.parse
import urllib.request

from helpers.stack import MAILPIT_URL


class Mailpit:
    def __init__(self, base_url: str = MAILPIT_URL):
        self.api = base_url + "/api/v1"

    def _request(self, method: str, path: str):
        req = urllib.request.Request(self.api + path, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
        return json.loads(body) if body else None

    def clear(self) -> None:
        self._request("DELETE", "/messages")

    def messages(self, query: str = "") -> list:
        """Message summaries, newest first (`query` uses Mailpit's search syntax, e.g. to:x@y)."""
        if query:
            return self._request("GET", "/search?" + urllib.parse.urlencode({"query": query}))["messages"]
        return self._request("GET", "/messages")["messages"]

    def message(self, message_id: str) -> dict:
        """Full message: Subject, From, To, Text, HTML, Attachments…"""
        return self._request("GET", f"/message/{message_id}")

    def wait_for(self, query: str = "", count: int = 1, timeout: float = 15) -> list:
        """Waits until at least `count` messages match, then returns them (full messages)."""
        deadline = time.monotonic() + timeout
        found = []
        while time.monotonic() < deadline:
            found = self.messages(query)
            if len(found) >= count:
                return [self.message(m["ID"]) for m in found]
            time.sleep(0.3)
        raise AssertionError(f"expected {count} e-mail(s) matching {query!r}, got {len(found)}")
