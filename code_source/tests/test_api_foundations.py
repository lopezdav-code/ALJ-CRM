"""Foundations of the API-only front end: SQLite middleware scope and ETag responses."""

import os
import sys
import unittest
from unittest.mock import patch

_src_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import server
from api.responses import json_with_etag


class TestSqliteCacheScope(unittest.TestCase):

    def test_uses_sqlite_cache(self):
        f = server.uses_sqlite_cache
        for path in ("/api/competitions", "/api/competitions/12/participants", "/api/coaches",
                     "/api/coaches/3", "/api/competition-members", "/api/helloasso/items",
                     "/api/helloasso/items/9/link", "/health", "/bureau/"):
            self.assertFalse(f(path), path)
        for path in ("/api/members", "/api/email-templates", "/api/helloasso/sync",
                     "/api/competitions-x", "/map", "/pivot"):
            self.assertTrue(f(path), path)

    def test_firestore_only_routes_skip_cache_refresh(self):
        """A competition request must not wait for the SQLite cache (full rebuild on a cold start)."""
        client = TestClient(server.app)
        env = {"ALJ_API_AUTH": "off", "K_SERVICE": "alj-escalade-api"}
        with patch.dict(os.environ, env), \
                patch.object(server.CloudDatabase, "is_enabled", return_value=True), \
                patch.object(server.CloudDatabase, "ensure_fresh") as fresh, \
                patch.object(server.CloudDatabase, "after_write") as after, \
                patch("api.competitions.Repo.list_competition_docs", return_value=[]), \
                patch("api.competitions.Repo.get_competition_doc", return_value=None):
            client.get("/api/competitions")
            client.post("/api/competitions/1/participants", json={"adherent_id": 2})
            fresh.assert_not_called()
            after.assert_not_called()
            client.get("/api/route-inconnue")
            fresh.assert_called_once()


def _app():
    app = FastAPI()

    @app.get("/data")
    def data(request: Request):
        return json_with_etag(request, {"nom": "Épreuve", "ids": [1, 2]})

    return TestClient(app)


class TestJsonWithEtag(unittest.TestCase):

    def test_etag_and_not_modified(self):
        client = _app()
        r = client.get("/data")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"nom": "Épreuve", "ids": [1, 2]})
        self.assertEqual(r.headers["cache-control"], "no-store")
        etag = r.headers["etag"]
        self.assertRegex(etag, r'^"[0-9a-f]{40}"$')
        r2 = client.get("/data", headers={"If-None-Match": etag})
        self.assertEqual(r2.status_code, 304)
        self.assertEqual(r2.content, b"")
        self.assertEqual(r2.headers["etag"], etag)
        self.assertEqual(client.get("/data", headers={"If-None-Match": f'"x", W/{etag}'}).status_code, 304)
        self.assertEqual(client.get("/data", headers={"If-None-Match": '"autre"'}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
