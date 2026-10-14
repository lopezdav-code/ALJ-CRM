"""Routes of src/api/coaches.py over the in-memory Firestore (auth off, local server)."""

from support.api_case import ApiTestCase

from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo


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
