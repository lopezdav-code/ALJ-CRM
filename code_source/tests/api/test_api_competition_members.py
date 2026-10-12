"""Routes of src/api/competition_members.py over the in-memory Firestore (auth off, local server)."""

from support.api_case import ApiTestCase


class TestCompetitionMembers(ApiTestCase):

    def test_projection(self):
        self.seed_adherent(1)
        members = self.client.get("/api/competition-members").json()
        self.assertEqual([(m["id"], m["nom"], m["licence_ffme"]) for m in members], [(1, "MARTIN", "654321")])
