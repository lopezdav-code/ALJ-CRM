"""Routes of src/api/participants.py over the in-memory Firestore (auth off, local server)."""

from support.api_case import ApiTestCase

from domain.competition_models import PAIEMENT_PAYE
from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo


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
