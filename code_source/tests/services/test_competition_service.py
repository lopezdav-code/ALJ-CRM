"""CompetitionService without HTTP: errors raised and list cache."""

from unittest.mock import patch

from support.fake_firestore import FirestoreRepoTestCase

from domain.competition_models import Competition
from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo
from infrastructure.firestore_client import FirestoreConflictError, FirestoreError
from services import competition_service
from services.competition_service import CompetitionService as Service
from services.errors import Conflict, InvalidRequest, NotFound, StorageUnavailable


class TestCompetitionService(FirestoreRepoTestCase):

    def setUp(self):
        super().setUp()
        competition_service.invalidate_cache()
        self.addCleanup(competition_service.invalidate_cache)

    def test_firestore_errors_become_service_errors(self):
        with patch.object(Repo, "list_competition_docs", side_effect=FirestoreError("down")):
            with self.assertRaises(StorageUnavailable):
                Service.list_competitions()
        with patch.object(Repo, "delete_competition", side_effect=FirestoreConflictError("race")):
            with self.assertRaises(Conflict) as ctx:
                Service.delete_competition(1)
        self.assertEqual(ctx.exception.code, "conflict")

    def test_business_errors_carry_their_code(self):
        with self.assertRaises(NotFound):
            Service.update_competition(404, {"nom": "X"})
        with self.assertRaises(InvalidRequest) as ctx:
            Service.ignore_helloasso_item(55, True, "", "", by="")
        self.assertEqual(ctx.exception.code, "motif_required")

    def test_list_is_cached_until_a_write(self):
        self.assertEqual(Service.list_competitions(), [])
        Repo.save_competition(Competition(id=1, nom="Hors service"))
        self.assertEqual(Service.list_competitions(), [])  # cached: written behind its back
        Service.create_competition({"nom": "Coupe"})
        self.assertEqual(len(Service.list_competitions()), 2)

    def test_failed_write_still_drops_the_cache(self):
        Service.list_competitions()
        with patch.object(Repo, "delete_competition", side_effect=FirestoreError("down")):
            with self.assertRaises(StorageUnavailable):
                Service.delete_competition(1)
        self.assertIsNone(competition_service._competitions_cache["docs"])
