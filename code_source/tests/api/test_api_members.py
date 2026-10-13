"""Routes of src/api/members.py and src/api/seasons.py over a temporary member database
(auth off, local server)."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from support.member_db import MemberDbTestCase

import server


class TestMemberRoutes(MemberDbTestCase):

    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {"ALJ_API_AUTH": "off"})
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(server.app)

    def test_seasons(self):
        r = self.client.get("/api/seasons")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"seasons": ["2026-2027", "2025-2026"], "active": "2026-2027"})

    def test_members_of_the_active_season_by_default(self):
        self.seed_planning("Loisir adultes", ["Loisir"], jour="Lundi", horaires="19h", type="Loisir")
        self.seed("1", "Léo", "MARTIN", "Loisir")
        self.seed("2", "Max", "PETIT", "Loisir", season="2025-2026")
        r = self.client.get("/api/members")
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["season"], "2026-2027")
        self.assertEqual([m["first_name"] for m in data["members"]], ["Léo"])
        leo = data["members"][0]
        self.assertEqual((leo["creneau_groupe"], leo["creneau_details"], leo["status_norm"]),
                         ("Loisir adultes", "Lundi 19h", "Validé"))
        self.assertTrue(leo["purchase_id"])
        self.assertEqual(data["creneaux"][0]["tarifs"], ["Loisir"])

        again = self.client.get("/api/members", headers={"If-None-Match": r.headers["etag"]})
        self.assertEqual(again.status_code, 304)

        past = self.client.get("/api/members", params={"season": "2025-2026"}).json()
        self.assertEqual([m["first_name"] for m in past["members"]], ["Max"])

    def test_unknown_season(self):
        r = self.client.get("/api/members", params={"season": "1999-2000"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["code"], "not_found")
