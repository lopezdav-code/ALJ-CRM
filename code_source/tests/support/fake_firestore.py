"""In-memory stand-in for FirestoreClient, shared by the repository and API tests."""

import unittest
from unittest.mock import patch

from infrastructure.firestore_client import FirestoreClient
from infrastructure import firestore_client as fc
from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo


class FakeFirestore:
    """Magasin de documents en mémoire imitant FirestoreClient."""

    META = ("_doc_id", "_update_time")

    def __init__(self):
        self.store = {}
        # Horodatage de version par document (imite `updateTime` de Firestore)
        self.versions = {}
        self._clock = 0
        # Crochet optionnel appelé juste avant une écriture conditionnelle
        # (simule une modification concurrente entre lecture et écriture).
        self.before_conditional_write = None

    def _col(self, collection_name):
        return self.store.setdefault(collection_name, {})

    def _touch(self, collection_name, doc_id):
        self._clock += 1
        self.versions[(collection_name, str(doc_id))] = f"2026-01-01T00:00:00.{self._clock:06d}Z"

    def _out(self, collection_name, doc_id, doc):
        out = dict(doc)
        out["_doc_id"] = str(doc_id)
        out["_update_time"] = self.versions.get((collection_name, str(doc_id)))
        return out

    def get_document(self, collection_name, doc_id, project_id=None, access_token=None):
        doc = self._col(collection_name).get(str(doc_id))
        if doc is None:
            return None
        return self._out(collection_name, doc_id, doc)

    def list_documents(self, collection_name, project_id=None, access_token=None):
        return [self._out(collection_name, doc_id, doc)
                for doc_id, doc in self._col(collection_name).items()]

    def upsert_document(self, collection_name, doc_id, data, project_id=None, access_token=None):
        self._col(collection_name)[str(doc_id)] = {k: v for k, v in data.items() if k not in self.META}
        self._touch(collection_name, doc_id)
        return True

    def update_fields(self, collection_name, doc_id, patch, project_id=None, access_token=None,
                      expected_update_time=None):
        if expected_update_time:
            hook = self.before_conditional_write
            if hook:
                hook(collection_name, doc_id)
            if self.versions.get((collection_name, str(doc_id))) != expected_update_time:
                raise fc.FirestoreConflictError("conflit simulé")
        doc = self._col(collection_name).setdefault(str(doc_id), {})
        doc.update({k: v for k, v in patch.items() if k not in self.META})
        self._touch(collection_name, doc_id)
        return True

    def delete_document(self, collection_name, doc_id, project_id=None, access_token=None):
        return self._col(collection_name).pop(str(doc_id), None) is not None

    def batch_upsert(self, writes, project_id=None, access_token=None):
        for w in writes:
            col, _, doc_id = str(w["path"]).partition("/")
            data = {k: v for k, v in (w.get("data") or {}).items() if k != "_doc_id"}
            mask = w.get("update_fields")
            if mask:  # updateMask : seuls les champs listés sont écrits
                doc = dict(self._col(col).get(doc_id) or {})
                for k in mask:
                    if k in data:
                        doc[k] = data[k]
                    else:
                        doc.pop(k, None)
                data = doc
            self._col(col)[doc_id] = data
        return {"written": len(writes), "errors_count": 0, "errors": []}


class FirestoreRepoTestCase(unittest.TestCase):
    """Base commune : FirestoreClient remplacé par le magasin en mémoire."""

    def setUp(self):
        self.fake = FakeFirestore()
        self._patches = [
            patch.object(FirestoreClient, "get_document", self.fake.get_document),
            patch.object(FirestoreClient, "list_documents", self.fake.list_documents),
            patch.object(FirestoreClient, "upsert_document", self.fake.upsert_document),
            patch.object(FirestoreClient, "update_fields", self.fake.update_fields),
            patch.object(FirestoreClient, "delete_document", self.fake.delete_document),
            patch.object(FirestoreClient, "batch_upsert", self.fake.batch_upsert),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)
        # Cache adhérents remis à zéro entre les tests
        Repo._invalidate_adherents_cache()
        self.addCleanup(Repo._invalidate_adherents_cache)

    def seed_adherent(self, aid, nom="MARTIN", prenom="Lucas", licence="654321",
                      tarif="Compétition U18", email="lucas.martin@test.fr"):
        Repo.COLLECTION_ADHERENTS and self.fake.upsert_document(
            Repo.COLLECTION_ADHERENTS, str(aid),
            {
                "id": aid, "nom": nom, "prenom": prenom, "licence_ffme": licence,
                "num_licence": licence, "email": email, "phone": "0600000000",
                "tarif": tarif, "creneau_groupe": tarif, "emergency_name": "Mère",
                "emergency_phone": "0611111111",
            },
        )
        Repo._invalidate_adherents_cache()
