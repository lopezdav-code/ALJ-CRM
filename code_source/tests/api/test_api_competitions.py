"""Routes of src/api/competitions.py over the in-memory Firestore (auth off, local server)."""

from unittest.mock import patch

from support.api_case import ApiTestCase

from domain.competition_models import Competition
from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo
from infrastructure.firestore_client import FirestoreError


class TestCompetitions(ApiTestCase):

    def test_create_list_and_etag(self):
        self.fake.upsert_document("coaches", "7", {"id": 7, "nom": "Alice"})
        doc = self.create(id_ffme="18846", date_competition="2026-03-15", prix=15,
                          coach_ids=[7], lieu="Lyon", type="Bloc")
        self.assertEqual(doc["coaches"], ["Alice"])
        self.assertEqual(doc["coach1_id"], 7)
        self.assertEqual((doc["lieu"], doc["type"]), ("Lyon", "Bloc"))  # pass-through fields
        self.assertEqual(doc["participants"], [])
        self.assertNotIn("_update_time", doc)

        r = self.client.get("/api/competitions")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c["id"] for c in r.json()], [doc["id"]])
        again = self.client.get("/api/competitions", headers={"If-None-Match": r.headers["etag"]})
        self.assertEqual(again.status_code, 304)

    def test_create_validation(self):
        for body in ({"nom": "  "}, {"nom": "A", "coach_ids": [1, 2, 3, 4]},
                     {"nom": "A", "statut": "inconnu"}, {"nom": "A", "date_competition": "15/03/2026"},
                     {"nom": "A", "prix": -1}, {"nom": "A", "champ_inconnu": 1}):
            self.assertEqual(self.client.post("/api/competitions", json=body).status_code, 422, body)

    def test_partial_update_keeps_other_fields(self):
        doc = self.create(id_ffme="18846", helloasso_ref="coupe-rhone", lieu="Lyon")
        r = self.client.patch(f"/api/competitions/{doc['id']}", json={"nom": "Coupe du Rhône"})
        self.assertEqual(r.status_code, 200, r.text)
        updated = r.json()
        self.assertEqual(updated["nom"], "Coupe du Rhône")
        self.assertEqual(updated["id_ffme"], "18846")
        self.assertEqual(updated["helloasso_ref"], "coupe-rhone")
        self.assertEqual(updated["lieu"], "Lyon")
        self.assertEqual(self.client.patch("/api/competitions/123", json={"nom": "X"}).status_code, 404)

    def test_update_keeps_participants(self):
        self.seed_adherent(1)
        doc = self.create()
        Repo.add_participant(doc["id"], 1)
        r = self.client.patch(f"/api/competitions/{doc['id']}", json={"statut": "close"})
        self.assertEqual(r.json()["statut"], "close")
        self.assertEqual(len(r.json()["participants"]), 1)

    def test_delete(self):
        doc = self.create()
        self.assertEqual(self.client.delete(f"/api/competitions/{doc['id']}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/competitions/{doc['id']}").status_code, 404)
        self.assertEqual(self.client.get("/api/competitions").json(), [])

    def test_archive_past(self):
        # Explicit ids: new ids are millisecond timestamps, equal within one test
        past = Repo.save_competition(Competition(id=1, nom="Passée", date_competition="2020-01-10"))
        two_days = Repo.save_competition(Competition(id=2, nom="Longue", date_competition="2020-01-10",
                                                     date_fin="2999-01-11"))
        undated = Repo.save_competition(Competition(id=3, nom="Sans date"))
        r = self.client.post("/api/competitions/archive-past")
        self.assertEqual(r.json()["archived"], [past])
        self.assertEqual(Repo.get_competition(past).statut, "close")
        self.assertEqual(Repo.get_competition(two_days).statut, "en_preparation")
        self.assertEqual(Repo.get_competition(undated).statut, "en_preparation")

    def test_firestore_failure(self):
        with patch.object(Repo, "list_competition_docs", side_effect=FirestoreError("down")):
            r = self.client.get("/api/competitions")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["code"], "unavailable")
