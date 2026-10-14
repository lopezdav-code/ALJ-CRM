"""Base test case of the API routes: in-memory Firestore, auth off, local server."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from support.fake_firestore import FirestoreRepoTestCase

import server
from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo
from services import competition_store


class ApiTestCase(FirestoreRepoTestCase):

    def setUp(self):
        super().setUp()
        env = patch.dict(os.environ, {"ALJ_API_AUTH": "off"})
        env.start()
        self.addCleanup(env.stop)
        competition_store.invalidate_cache()
        self.addCleanup(competition_store.invalidate_cache)
        self.client = TestClient(server.app)

    def create(self, **body):
        body.setdefault("nom", "Coupe Rhône")
        r = self.client.post("/api/competitions", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def participant(self, comp_id, adherent_id):
        doc = Repo.get_competition_doc(comp_id)
        return next(p for p in doc["participants"] if p["adherent_id"] == adherent_id)
