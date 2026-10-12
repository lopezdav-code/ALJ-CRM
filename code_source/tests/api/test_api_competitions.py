"""Routes of src/api/competitions.py (and services/competition_service.py) over the in-memory Firestore (auth off, local server)."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from support.fake_firestore import FirestoreRepoTestCase

import server
from domain.competition_models import Competition, PAIEMENT_PAYE
from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo
from infrastructure.firestore_client import FirestoreError
from services import competition_service


class ApiTestCase(FirestoreRepoTestCase):

    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {"ALJ_API_AUTH": "off"})
        env.start()
        self.addCleanup(env.stop)
        competition_service.invalidate_cache()
        self.addCleanup(competition_service.invalidate_cache)
        self.client = TestClient(server.app)

    def create(self, **body):
        body.setdefault("nom", "Coupe Rhône")
        r = self.client.post("/api/competitions", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def participant(self, comp_id, adherent_id):
        doc = Repo.get_competition_doc(comp_id)
        return next(p for p in doc["participants"] if p["adherent_id"] == adherent_id)


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


class TestParticipants(ApiTestCase):

    def setUp(self):
        super().setUp()
        self.seed_adherent(1)
        self.seed_adherent(2, nom="DURAND", prenom="Léa", tarif="Loisir adulte")
        self.comp = self.create()["id"]

    def url(self, suffix=""):
        return f"/api/competitions/{self.comp}/participants{suffix}"

    def test_add_select_unselect(self):
        r = self.client.post(self.url(), json={"adherent_id": 1})
        self.assertEqual(r.status_code, 200, r.text)
        p = self.participant(self.comp, 1)
        self.assertTrue(p["selectionne"])
        self.assertEqual(p["statut_paiement"], "en_attente")
        self.assertEqual(r.json()["nb_selectionnes"], 1)

        r = self.client.patch(self.url("/1"), json={"selectionne": False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.participant(self.comp, 1)["statut_paiement"], "non_invite")
        self.assertEqual(self.client.post("/api/competitions/999/participants",
                                          json={"adherent_id": 1}).status_code, 404)

    def test_unselect_paid_participant_needs_cancellation(self):
        Repo.add_participant(self.comp, 1)
        Repo.set_payment_status(self.comp, 1, PAIEMENT_PAYE)
        r = self.client.patch(self.url("/1"), json={"selectionne": False})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["code"], "already_paid")
        self.assertTrue(self.participant(self.comp, 1)["selectionne"])

        r = self.client.post(self.url("/1/cancel"), json={"mode": "reporte", "note": "Blessure"})
        self.assertEqual(r.status_code, 200, r.text)
        p = self.participant(self.comp, 1)
        self.assertEqual((p["selectionne"], p["statut_paiement"], p["note_paiement"]),
                         (False, "annule_reporte", "Blessure"))

    def test_cancel_validation(self):
        Repo.add_participant(self.comp, 1)
        self.assertEqual(self.client.post(self.url("/1/cancel"),
                                          json={"mode": "rembourse", "note": "x"}).status_code, 422)
        self.assertEqual(self.client.post(self.url("/1/cancel"),
                                          json={"mode": "perdu", "note": " "}).status_code, 422)
        self.assertEqual(self.client.post(self.url("/2/cancel"),
                                          json={"mode": "perdu", "note": "x"}).status_code, 404)

    def test_present_flag_and_remove(self):
        Repo.add_participant(self.comp, 1)
        self.assertEqual(self.client.patch(self.url("/1"), json={"present": True}).status_code, 200)
        self.assertTrue(self.participant(self.comp, 1)["present"])
        self.assertEqual(self.client.patch(self.url("/2"), json={"present": True}).status_code, 404)

        self.assertEqual(self.client.delete(self.url("/1")).status_code, 200)
        self.assertEqual(Repo.get_competition_doc(self.comp)["participants"], [])
        self.assertEqual(self.client.delete(self.url("/1")).status_code, 404)

    def test_load_group(self):
        r = self.client.post(f"/api/competitions/{self.comp}/load-group")
        self.assertEqual(r.json()["added"], 1)  # only the « Compétition » tariff member
        self.assertEqual(self.participant(self.comp, 1)["statut_paiement"], "non_invite")
        self.assertEqual(self.client.post(f"/api/competitions/{self.comp}/load-group").json()["added"], 0)


class TestCoaches(ApiTestCase):

    def test_crud_and_cascade(self):
        r = self.client.post("/api/coaches", json={"nom": "Alice"})
        self.assertEqual(r.status_code, 201)
        coach = r.json()["id"]
        comp = self.create(coach_ids=[coach])["id"]

        self.assertEqual(self.client.put(f"/api/coaches/{coach}", json={"nom": "Alicia"}).status_code, 200)
        self.assertEqual(Repo.get_competition_doc(comp)["coaches"], ["Alicia"])
        self.assertEqual(self.client.get("/api/coaches").json(), [{"id": coach, "nom": "Alicia"}])

        self.assertEqual(self.client.delete(f"/api/coaches/{coach}").status_code, 200)
        doc = Repo.get_competition_doc(comp)
        self.assertEqual((doc["coach_ids"], doc["coach1_id"], doc["coaches"]), ([], None, []))
        self.assertEqual(self.client.delete(f"/api/coaches/{coach}").status_code, 404)
        self.assertEqual(self.client.put("/api/coaches/1", json={"nom": "X"}).status_code, 404)
        self.assertEqual(self.client.post("/api/coaches", json={"nom": ""}).status_code, 422)


class TestHelloAssoItems(ApiTestCase):

    def setUp(self):
        super().setUp()
        self.seed_adherent(1)
        self.comp = self.create(prix=15)["id"]
        self.fake.upsert_document("helloasso_items", "55", {
            "id_item": 55, "order_id": 9001, "montant": 15.0, "etat": "Processed",
            "date_item": "2026-03-01", "competition_id": None, "adherent_id": None,
            "source": None, "commentaire": ""})

    def link(self, **body):
        return self.client.put("/api/helloasso/items/55/link", json=body)

    def test_list_items(self):
        items = self.client.get("/api/helloasso/items").json()
        self.assertEqual([i["id_item"] for i in items], [55])
        self.assertNotIn("_doc_id", items[0])

    def test_link_records_payment_once(self):
        r = self.link(competition_id=self.comp, adherent_id=1, commentaire="ok")
        self.assertEqual(r.status_code, 200, r.text)
        item = Repo.get_item(55)
        self.assertEqual((item["source"], item["commentaire"]), ("manuel", "ok"))
        p = self.participant(self.comp, 1)
        self.assertEqual((p["selectionne"], p["statut_paiement"], p["montant_paye"], p["commande_helloasso"]),
                         (True, "paye", 15.0, "9001"))
        # Saving the same link again does not count the amount twice (plan A1)
        self.link(competition_id=self.comp, adherent_id=1)
        self.assertEqual(self.participant(self.comp, 1)["montant_paye"], 15.0)

    def test_partial_link_and_errors(self):
        self.assertEqual(self.link(competition_id=self.comp).status_code, 200)
        item = Repo.get_item(55)
        self.assertEqual((item["competition_id"], item["adherent_id"], item["source"]), (self.comp, None, None))
        self.assertEqual(Repo.get_competition_doc(self.comp)["participants"], [])
        self.assertEqual(self.link(competition_id=999, adherent_id=1).status_code, 404)
        self.assertEqual(self.client.put("/api/helloasso/items/77/link", json={}).status_code, 404)

    def test_ignore_and_restore(self):
        url = "/api/helloasso/items/55/ignore"
        r = self.client.put(url, json={"ignore": True})
        self.assertEqual((r.status_code, r.json()["code"]), (400, "motif_required"))
        self.assertEqual(self.client.put(url, json={"ignore": True, "motif": "Test"}).status_code, 200)
        item = Repo.get_item(55)
        self.assertEqual((item["ignore"], item["ignore_motif"], item["commentaire"]), (True, "Test", "Test"))
        self.assertEqual(self.client.put(url, json={"ignore": False, "commentaire": "Erreur"}).status_code, 200)
        item = Repo.get_item(55)
        self.assertEqual((item["ignore"], item["ignore_motif"], item["commentaire"]), (False, "", "Erreur"))

    def test_linked_item_cannot_be_ignored(self):
        self.link(competition_id=self.comp, adherent_id=1)
        r = self.client.put("/api/helloasso/items/55/ignore", json={"ignore": True, "motif": "Test"})
        self.assertEqual((r.status_code, r.json()["code"]), (409, "already_linked"))

    def test_ignore_sees_link_made_meanwhile(self):
        """The webhook links the item between the read and the write: the retry sees it."""
        def webhook_links(collection, doc_id):
            self.fake.before_conditional_write = None
            Repo.set_item_link(55, self.comp, 1, source="webhook")
        self.fake.before_conditional_write = webhook_links
        r = self.client.put("/api/helloasso/items/55/ignore", json={"ignore": True, "motif": "Test"})
        self.assertEqual(r.status_code, 409)
        self.assertNotEqual(Repo.get_item(55).get("ignore"), True)


class TestCompetitionMembers(ApiTestCase):

    def test_projection(self):
        self.seed_adherent(1)
        members = self.client.get("/api/competition-members").json()
        self.assertEqual([(m["id"], m["nom"], m["licence_ffme"]) for m in members], [(1, "MARTIN", "654321")])


if __name__ == "__main__":
    unittest.main()
