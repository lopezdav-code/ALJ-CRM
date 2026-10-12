"""Routes of src/api/helloasso_items.py over the in-memory Firestore (auth off, local server)."""

from support.api_case import ApiTestCase

from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo


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
