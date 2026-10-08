"""
Tests unitaires pour le référentiel des compétitions sur Firestore
(competition_firestore_repository.py), avec client Firestore simulé en mémoire.
"""

import os
import sys
import unittest
from unittest.mock import patch

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_tests_dir), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from infrastructure.firestore_client import FirestoreClient
from infrastructure import firestore_client as fc
from infrastructure import competition_firestore_repository as repo_module
from infrastructure.competition_firestore_repository import CompetitionFirestoreRepository as Repo
from domain.competition_models import (
    Competition,
    statut_paiement_apres_bascule,
    PAIEMENT_NON_INVITE,
    PAIEMENT_EN_ATTENTE,
    PAIEMENT_PAYE,
    PAIEMENT_ANNULE_PERDU,
    PAIEMENT_ANNULE_REPORTE,
)


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
            self._col(col)[doc_id] = {k: v for k, v in (w.get("data") or {}).items() if k != "_doc_id"}
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
        repo_module.CompetitionFirestoreRepository._invalidate_adherents_cache()
        self.addCleanup(repo_module.CompetitionFirestoreRepository._invalidate_adherents_cache)

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


class TestCompetitionsCrud(FirestoreRepoTestCase):
    def test_create_edit_list_delete(self):
        comp = Competition(nom="Coupe Rhône", id_ffme="18846", date_competition="2026-03-15",
                           prix=15.0)
        comp_id = Repo.save_competition(comp)
        self.assertTrue(comp_id)
        self.assertIn(str(comp_id), self.fake.store["competitions"])

        got = Repo.get_competition(comp_id)
        self.assertEqual(got.nom, "Coupe Rhône")
        self.assertEqual(got.doc_id, str(comp_id))

        got.prix = 18.0
        Repo.save_competition(got)
        self.assertEqual(Repo.get_competition(comp_id).prix, 18.0)
        # Une seule documentation de l'épreuve (pas de doublon)
        self.assertEqual(len(self.fake.store["competitions"]), 1)

        comps = Repo.list_competitions()
        self.assertEqual(len(comps), 1)
        self.assertTrue(Repo.delete_competition(comp_id))
        self.assertEqual(Repo.list_competitions(), [])
        self.assertFalse(Repo.delete_competition(comp_id))

    def test_set_competition_status(self):
        comp_id = Repo.save_competition(Competition(nom="Test"))
        self.assertTrue(Repo.set_competition_status(comp_id, "en_cours"))
        self.assertEqual(Repo.get_competition(comp_id).statut, "en_cours")

    def test_coach_fields_roundtrip(self):
        cid = Repo.save_coach("Adrien BERGER")
        comp_id = Repo.save_competition(Competition(nom="Épreuve", coach1_id=cid))
        got = Repo.get_competition(comp_id)
        self.assertEqual(got.coach1_id, cid)
        self.assertIsNone(got.coach2_id)

    def test_legacy_doc_normalized_on_read(self):
        """Un document hérité (ID Firestore aléatoire) est recopié vers str(id)."""
        legacy_doc = {
            "id": 42, "nom": "Épreuve web", "prix": 10.0, "statut": "en_preparation",
            "participants": [], "coach_ids": [], "coaches": [],
            "updated_at": "2026-01-02T10:00:00", "created_at": "2026-01-02T10:00:00",
        }
        self.fake.store["competitions"] = {"randomLegacyId": dict(legacy_doc)}
        comp = Repo.get_competition(42)
        self.assertEqual(comp.nom, "Épreuve web")
        self.assertEqual(comp.doc_id, "42")
        self.assertNotIn("randomLegacyId", self.fake.store["competitions"])
        self.assertIn("42", self.fake.store["competitions"])

    def test_duplicate_docs_kept_newest(self):
        """Deux documents pour le même id : le plus récent gagne, l'autre est supprimé."""
        self.fake.store["competitions"] = {
            "7": {"id": 7, "nom": "Ancienne", "participants": [], "coach_ids": [],
                  "updated_at": "2026-01-01T00:00:00"},
            "legacy7": {"id": 7, "nom": "Récente", "participants": [], "coach_ids": [],
                        "updated_at": "2026-01-05T00:00:00"},
        }
        comps = Repo.list_competitions()
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].nom, "Récente")
        self.assertEqual(self.fake.store["competitions"]["7"]["nom"], "Récente")
        self.assertNotIn("legacy7", self.fake.store["competitions"])


class TestParticipants(FirestoreRepoTestCase):
    def setUp(self):
        super().setUp()
        self.seed_adherent(101)
        self.seed_adherent(102, nom="DUPONT", prenom="Léa", licence="111222",
                           tarif="Loisir")
        self.comp_id = Repo.save_competition(Competition(nom="Épreuve A", prix=15.0))

    def test_add_selection_payment_remove(self):
        Repo.add_participant(self.comp_id, 101)
        parts = Repo.list_participants(self.comp_id)
        self.assertEqual(len(parts), 1)
        p = parts[0]
        self.assertEqual(p.adherent_id, 101)
        self.assertTrue(p.selectionne)
        self.assertEqual(p.statut_paiement, "en_attente")
        self.assertEqual(p.tarif, "Compétition U18")

        # Idempotent : pas de doublon
        Repo.add_participant(self.comp_id, 101)
        self.assertEqual(len(Repo.list_participants(self.comp_id)), 1)

        self.assertTrue(Repo.set_selection(self.comp_id, 101, False))
        self.assertFalse(Repo.list_participants(self.comp_id)[0].selectionne)

        self.assertTrue(Repo.set_payment_status(self.comp_id, 101, "paye"))
        p = Repo.list_participants(self.comp_id)[0]
        self.assertEqual(p.statut_paiement, "paye")

        self.assertTrue(Repo.apply_helloasso_payment(self.comp_id, 101, 15.0,
                                                     order_ref="CMD-1"))
        p = Repo.list_participants(self.comp_id)[0]
        self.assertEqual(p.montant_paye, 15.0)
        self.assertEqual(p.commande_helloasso, "CMD-1")
        self.assertTrue(p.date_synchro_helloasso)

        self.assertTrue(Repo.remove_participant(self.comp_id, 101))
        self.assertFalse(Repo.remove_participant(self.comp_id, 101))
        self.assertEqual(Repo.list_participants(self.comp_id), [])

    def test_set_selection_creates_missing_participant(self):
        self.assertTrue(Repo.set_selection(self.comp_id, 102, True))
        parts = Repo.list_participants(self.comp_id)
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].adherent_id, 102)

    def test_load_competition_group_only_competition_tarifs(self):
        n = Repo.load_competition_group_into(self.comp_id)
        self.assertEqual(n, 1)  # seul MARTIN a un tarif « Compétition »
        parts = Repo.list_participants(self.comp_id)
        self.assertEqual(len(parts), 1)
        p = parts[0]
        self.assertEqual(p.adherent_id, 101)
        self.assertFalse(p.selectionne)
        self.assertEqual(p.statut_paiement, PAIEMENT_NON_INVITE)

    def test_list_participants_selected_only(self):
        Repo.add_participant(self.comp_id, 101, selectionne=True)
        Repo.add_participant(self.comp_id, 102, selectionne=False)
        self.assertEqual(len(Repo.list_participants(self.comp_id, selected_only=True)), 1)
        self.assertEqual(len(Repo.list_participants(self.comp_id)), 2)

    def test_unknown_competition(self):
        self.assertEqual(Repo.list_participants(9999), [])
        self.assertFalse(Repo.remove_participant(9999, 101))


class TestBilan(FirestoreRepoTestCase):
    def setUp(self):
        super().setUp()
        self.seed_adherent(101)
        self.comp_id = Repo.save_competition(
            Competition(nom="Épreuve", date_competition="2026-03-15", prix=15.0))
        Repo.set_selection(self.comp_id, 101, True)

    def test_season_of_date(self):
        self.assertEqual(Repo.season_of_date("2026-03-15"), "2025-2026")
        self.assertEqual(Repo.season_of_date("2026-09-15"), "2026-2027")
        self.assertEqual(Repo.season_of_date(""), "")

    def test_bilan_pivot_and_seasons(self):
        bilan = Repo.get_bilan()
        self.assertEqual(len(bilan["competitions"]), 1)
        self.assertIn((101, self.comp_id), bilan["participations"])
        self.assertEqual(bilan["participations"][(101, self.comp_id)], "en_attente")
        self.assertEqual(bilan["payments"][(101, self.comp_id)]["prix"], 15.0)
        self.assertEqual(bilan["seasons"], ["2025-2026"])
        stu = bilan["students"][101]
        self.assertEqual(stu["nom"], "MARTIN")
        self.assertEqual(stu["num_licence"], "654321")

        empty = Repo.get_bilan("2030-2031")
        self.assertEqual(empty["competitions"], [])
        self.assertEqual(empty["students"], {})

    def test_deselected_participant_excluded_from_bilan(self):
        Repo.set_selection(self.comp_id, 101, False)
        bilan = Repo.get_bilan()
        self.assertNotIn((101, self.comp_id), bilan["participations"])


class TestCoaches(FirestoreRepoTestCase):
    def test_crud_and_competition_propagation(self):
        cid = Repo.save_coach("Adrien BERGER")
        self.assertEqual(Repo.get_coach(cid)["nom"], "Adrien BERGER")
        self.assertEqual([c["nom"] for c in Repo.list_coaches()], ["Adrien BERGER"])

        comp_id = Repo.save_competition(Competition(nom="Épreuve", coach1_id=cid))
        self.assertEqual([c.id for c in Repo.list_competitions_for_coach(cid)], [comp_id])
        self.assertEqual([c.id for c in Repo.list_competitions_for_coach(9999)], [])

        Repo.save_coach("Adrien BERGERAT", coach_id=cid)
        comp_doc = self.fake.store["competitions"][str(comp_id)]
        self.assertIn("Adrien BERGERAT", comp_doc["coaches"])

        self.assertTrue(Repo.delete_coach(cid))
        comp_doc = self.fake.store["competitions"][str(comp_id)]
        self.assertEqual(comp_doc["coach_ids"], [])
        self.assertEqual(Repo.get_competition(comp_id).coach1_id, None)


class TestHelloAssoMirror(FirestoreRepoTestCase):
    def setUp(self):
        super().setUp()
        self.seed_adherent(101, licence="654321")
        self.comp_id = Repo.save_competition(
            Competition(nom="Coupe Rhône", id_ffme="18846", date_competition="2026-03-15"))
        self.summary = [{
            "id_item": 500, "payeur": "Lucas MARTIN", "montant": 15.0, "etat": "Validated",
            "date_item": "2026-02-01", "licence": "654321", "competition": "Coupe Rhône",
            "commande": "8888",
        }]
        self.raw = [{"id": 500, "amount": 1500}]
        Repo.sync_helloasso_mirror(self.summary, self.raw, "campagne-2026")

    def test_mirror_upsert_preserves_comment_and_link(self):
        written = Repo.sync_helloasso_mirror(self.summary, self.raw, "campagne-2026")
        self.assertEqual(written, 1)

        Repo.save_item_comment(500, "Régularisation")
        Repo.set_item_link(500, self.comp_id, 101, source="manuel")

        # Re-synchronisation : le commentaire et le lien sont conservés
        Repo.sync_helloasso_mirror(self.summary, self.raw, "campagne-2026")
        it = Repo.get_item(500)
        self.assertEqual(it["commentaire"], "Régularisation")
        self.assertEqual(it["competition_id"], self.comp_id)
        self.assertEqual(it["adherent_id"], 101)
        self.assertEqual(it["source"], "manuel")
        self.assertEqual(it["montant"], 15.0)
        self.assertEqual(str(it["order_id"]), "8888")

    def test_links_listing_and_clear(self):
        links = Repo.list_helloasso_links()
        self.assertEqual(links, {})
        Repo.set_item_link(500, self.comp_id, 101, source="manuel")
        links = Repo.list_helloasso_links()
        self.assertEqual(links[500]["source"], "manuel")

        self.assertTrue(Repo.clear_item_link(500))
        self.assertEqual(Repo.list_helloasso_links(), {})
        it = Repo.get_item(500)
        self.assertIsNone(it["competition_id"])

    def test_replace_auto_links_preserves_manual(self):
        other_id = Repo.save_competition(Competition(nom="Autre épreuve", id_ffme="9999"))
        item2 = [{"id_item": 501, "payeur": "Léa DUPONT", "montant": 10.0, "etat": "Validated",
                  "date_item": "2026-02-02", "licence": "111222", "competition": "",
                  "commande": "7777"}]
        Repo.sync_helloasso_mirror(item2, [{"id": 501}], "campagne-2026")

        Repo.replace_auto_links({
            500: {"competition_id": self.comp_id, "adherent_id": 101, "source": "auto"},
            501: {"competition_id": other_id, "adherent_id": None, "source": "auto"},
        })
        # Lien manuel posé ensuite sur 501 : non écrasé lors de la resynchronisation
        Repo.set_item_link(501, other_id, None, source="manuel")
        Repo.replace_auto_links({
            500: {"competition_id": self.comp_id, "adherent_id": 101, "source": "auto"},
        })
        it500 = Repo.get_item(500)
        self.assertEqual(it500["source"], "auto")
        self.assertEqual(it500["competition_id"], self.comp_id)
        it501 = Repo.get_item(501)
        self.assertEqual(it501["source"], "manuel")

    def test_apply_links_to_participants_aggregates(self):
        item2 = [{"id_item": 501, "payeur": "Lucas MARTIN", "montant": 15.0,
                  "etat": "Validated", "date_item": "2026-02-02", "licence": "654321",
                  "competition": "Coupe Rhône", "commande": "9999"}]
        Repo.sync_helloasso_mirror(item2, [{"id": 501}], "campagne-2026")
        Repo.set_item_link(500, self.comp_id, 101, source="auto")
        Repo.set_item_link(501, self.comp_id, 101, source="auto")

        applied = Repo.apply_links_to_participants()
        self.assertEqual(applied, 1)
        p = Repo.list_participants(self.comp_id)[0]
        self.assertEqual(p.statut_paiement, "paye")
        self.assertEqual(p.montant_paye, 30.0)
        self.assertEqual(p.commande_helloasso, "8888, 9999")
        self.assertTrue(p.selectionne)

    def test_unlinked_items_listing(self):
        Repo.set_item_link(500, self.comp_id, None, source="auto")
        unlinked = Repo.list_unlinked_items()
        self.assertEqual(len(unlinked), 1)
        row = unlinked[0]
        self.assertEqual(row["id_item"], 500)
        self.assertEqual(row["adherent_id"], 101)  # pré-sélection par licence

        Repo.set_item_link(500, self.comp_id, 101, source="auto")
        self.assertEqual(Repo.list_unlinked_items(), [])


class TestAppSettings(FirestoreRepoTestCase):
    def test_settings_roundtrip(self):
        self.assertEqual(Repo.get_app_setting("HELLOASSO_ANNUAL_CAMPAIGN"), "")
        Repo.save_app_setting("HELLOASSO_ANNUAL_CAMPAIGN", "competition-saison-2026")
        self.assertEqual(Repo.get_app_setting("HELLOASSO_ANNUAL_CAMPAIGN"),
                         "competition-saison-2026")
        Repo.save_app_setting("HELLOASSO_ANNUAL_CAMPAIGN", "")
        self.assertEqual(Repo.get_app_setting("HELLOASSO_ANNUAL_CAMPAIGN"), "")


class TestAdherents(FirestoreRepoTestCase):
    def test_listing_and_search(self):
        self.seed_adherent(101, licence="654321")
        self.seed_adherent(102, nom="DUPONT", prenom="Léa", licence="111222", tarif="Loisir")
        adhs = Repo.list_adherents()
        self.assertEqual(len(adhs), 2)
        by_id = {a["id"]: a for a in adhs}
        self.assertEqual(by_id[101]["num_licence"], "654321")

        self.assertEqual(len(Repo.list_adherents(search="dupont")), 1)
        self.assertEqual(len(Repo.list_adherents(competition_only=True)), 1)
        self.assertEqual(Repo.count_adherents(), 2)


class TestBatchUpsertCommitBody(unittest.TestCase):
    """Régression : :commit exige un nom de document RELATIF (projects/…/documents/…),
    pas une URL complète (HTTP 400 « lacks projects » vu en production)."""

    def test_commit_uses_relative_document_name(self):
        import json as _json
        with patch.object(fc.requests, "post") as mock_post, \
             patch.object(FirestoreClient, "get_access_token", return_value="fake-token"):
            resp = mock_post.return_value
            resp.status_code = 200
            report = FirestoreClient.batch_upsert(
                [{"path": "adherents/131", "data": {"nom": "DUPONT"}}],
                project_id="smart-amplifier-510811-n6",
            )
        self.assertEqual(report["written"], 1)
        self.assertEqual(report["errors_count"], 0)
        body = mock_post.call_args.kwargs["json"]
        name = body["writes"][0]["update"]["name"]
        self.assertTrue(name.startswith("projects/"), name)
        self.assertEqual(
            name,
            "projects/smart-amplifier-510811-n6/databases/(default)/documents/adherents/131",
        )
        # Le :commit est bien appelé sur l'URL absolue du service
        self.assertIn("https://firestore.googleapis.com/v1/", mock_post.call_args.args[0])
        self.assertIn(":commit", mock_post.call_args.args[0])


class TestModificationsConcurrentes(FirestoreRepoTestCase):
    """Verrouillage optimiste des participants : une écriture concurrente
    (autre poste, page web, webhook HelloAsso) n'est jamais perdue."""

    def setUp(self):
        super().setUp()
        self.seed_adherent(101)
        self.seed_adherent(102, nom="DUPONT", prenom="Léa", licence="111222")
        self.comp_id = Repo.save_competition(Competition(nom="Épreuve C", prix=15.0))
        Repo.add_participant(self.comp_id, 101)
        Repo.add_participant(self.comp_id, 102)

    def _parts(self):
        return {p.adherent_id: p for p in Repo.list_participants(self.comp_id)}

    def _concurrent_once(self, action):
        """Exécute `action` (écriture directe) une seule fois, juste avant la
        prochaine écriture conditionnelle du référentiel."""
        state = {"done": False}

        def hook(collection_name, doc_id):
            if state["done"]:
                return
            state["done"] = True
            self.fake.before_conditional_write = None
            action()
        self.fake.before_conditional_write = hook
        return state

    def test_paiement_concurrent_preserve_par_la_selection(self):
        # Pendant que le bureau décoche 102, le webhook HelloAsso marque 101 payé.
        def webhook():
            doc = self.fake.store["competitions"][str(self.comp_id)]
            parts = [dict(p) for p in doc["participants"]]
            for p in parts:
                if p["adherent_id"] == 101:
                    p["statut_paiement"] = "paye"
                    p["montant_paye"] = 15.0
            self.fake.update_fields("competitions", str(self.comp_id), {"participants": parts})
        state = self._concurrent_once(webhook)
        Repo.set_selection(self.comp_id, 102, False)
        self.assertTrue(state["done"])
        parts = self._parts()
        self.assertEqual(parts[101].statut_paiement, PAIEMENT_PAYE)   # pas écrasé
        self.assertEqual(parts[101].montant_paye, 15.0)
        self.assertFalse(parts[102].selectionne)                       # modification rejouée
        doc = self.fake.store["competitions"][str(self.comp_id)]
        self.assertEqual(doc["nb_payes"], 1)
        self.assertEqual(doc["total_collecte"], 15.0)

    def test_ajout_concurrent_preserve(self):
        self.seed_adherent(103, nom="BERNARD", prenom="Tom", licence="333444")
        state = self._concurrent_once(lambda: Repo.add_participant(self.comp_id, 103))
        Repo.apply_helloasso_payment(self.comp_id, 101, 15.0, order_ref="ORD-1")
        self.assertTrue(state["done"])
        parts = self._parts()
        self.assertIn(103, parts)
        self.assertEqual(parts[101].statut_paiement, PAIEMENT_PAYE)

    def test_conflit_persistant_leve_une_erreur(self):
        def always(collection_name, doc_id):
            self.fake._touch(collection_name, doc_id)
        self.fake.before_conditional_write = always
        with patch.object(repo_module.time, "sleep"):
            with self.assertRaises(fc.FirestoreConflictError):
                Repo.set_payment_status(self.comp_id, 101, PAIEMENT_PAYE)

    def test_modification_epreuve_ne_reecrit_pas_les_participants(self):
        comp = Repo.get_competition(self.comp_id)          # lu avant le paiement
        Repo.apply_helloasso_payment(self.comp_id, 101, 15.0)
        comp.prix = 20.0
        Repo.save_competition(comp)
        self.assertEqual(Repo.get_competition(self.comp_id).prix, 20.0)
        self.assertEqual(self._parts()[101].statut_paiement, PAIEMENT_PAYE)

    def test_add_participant_retourne_l_identifiant(self):
        self.seed_adherent(104, nom="PETIT", prenom="Zoé", licence="555666")
        self.assertEqual(Repo.add_participant(self.comp_id, 104), 104)


class TestFirestoreClientPrecondition(unittest.TestCase):
    """Client REST : précondition `currentDocument.updateTime` et clés techniques."""

    def test_meta_keys_jamais_ecrites(self):
        fields = fc.dict_to_firestore_fields({"nom": "A", "_doc_id": "1", "_update_time": "t"})
        self.assertEqual(list(fields), ["nom"])

    def test_update_fields_envoie_la_precondition(self):
        with patch.object(fc.requests, "patch") as mock_patch, \
             patch.object(FirestoreClient, "get_access_token", return_value="tok"):
            mock_patch.return_value.status_code = 200
            FirestoreClient.update_fields("competitions", "1", {"x": 1, "_update_time": "T"},
                                          project_id="p", expected_update_time="T0")
        params = mock_patch.call_args.kwargs["params"]
        self.assertIn(("currentDocument.updateTime", "T0"), params)
        self.assertEqual([v for k, v in params if k == "updateMask.fieldPaths"], ["x"])

    def test_update_fields_conflit(self):
        with patch.object(fc.requests, "patch") as mock_patch, \
             patch.object(FirestoreClient, "get_access_token", return_value="tok"):
            mock_patch.return_value.status_code = 400
            mock_patch.return_value.text = '{"error": {"status": "FAILED_PRECONDITION"}}'
            with self.assertRaises(fc.FirestoreConflictError):
                FirestoreClient.update_fields("competitions", "1", {"x": 1},
                                              project_id="p", expected_update_time="T0")
            # Sans précondition, une erreur 400 reste une erreur générique
            with self.assertRaises(fc.FirestoreError) as ctx:
                FirestoreClient.update_fields("competitions", "1", {"x": 1}, project_id="p")
            self.assertNotIsInstance(ctx.exception, fc.FirestoreConflictError)


class TestBasculeParticipePaiement(unittest.TestCase):
    """Règle de liaison « Participe » ↔ statut de paiement (hors décisions coach)."""

    def test_checking(self):
        self.assertEqual(statut_paiement_apres_bascule(PAIEMENT_NON_INVITE, True), PAIEMENT_EN_ATTENTE)
        self.assertIsNone(statut_paiement_apres_bascule(PAIEMENT_EN_ATTENTE, True))
        self.assertIsNone(statut_paiement_apres_bascule(PAIEMENT_PAYE, True))
        # Réactivation d'un annulé : retour « payé » (l'argent est déjà là)
        self.assertEqual(statut_paiement_apres_bascule(PAIEMENT_ANNULE_REPORTE, True), PAIEMENT_PAYE)
        self.assertEqual(statut_paiement_apres_bascule(PAIEMENT_ANNULE_PERDU, True), PAIEMENT_PAYE)
        # Statut inconnu/vide traité comme « non invité » -> « en attente »
        self.assertEqual(statut_paiement_apres_bascule(None, True), PAIEMENT_EN_ATTENTE)

    def test_unchecking(self):
        self.assertEqual(statut_paiement_apres_bascule(PAIEMENT_EN_ATTENTE, False), PAIEMENT_NON_INVITE)
        self.assertIsNone(statut_paiement_apres_bascule(PAIEMENT_NON_INVITE, False))
        # « payé » décoché = décision coach (dialog reporter/encaisser), pas de statut auto
        self.assertIsNone(statut_paiement_apres_bascule(PAIEMENT_PAYE, False))
        self.assertIsNone(statut_paiement_apres_bascule(PAIEMENT_ANNULE_REPORTE, False))


class TestAnnulationParticipantPaye(FirestoreRepoTestCase):
    """Annulation d'un participant ayant payé : report = crédit, perdu = écarté."""

    def setUp(self):
        super().setUp()
        self.seed_adherent(101)
        self.comp_id = Repo.save_competition(
            Competition(nom="Épreuve", date_competition="2026-03-15", prix=15.0))
        Repo.add_participant(self.comp_id, 101, selectionne=True)
        Repo.apply_helloasso_payment(self.comp_id, 101, 15.0, order_ref="CMD-1")

    def test_annule_reporte_garde_le_montant_en_credit(self):
        self.assertTrue(Repo.mark_cancelled(self.comp_id, 101, PAIEMENT_ANNULE_REPORTE, "blessure"))
        p = Repo.list_participants(self.comp_id)[0]
        self.assertFalse(p.selectionne)
        self.assertEqual(p.statut_paiement, PAIEMENT_ANNULE_REPORTE)
        self.assertEqual(p.montant_paye, 15.0)
        self.assertEqual(p.note_paiement, "blessure")

        bilan = Repo.get_bilan()
        # Pas de participation due
        self.assertNotIn((101, self.comp_id), bilan["participations"])
        # Mais un crédit : montant payé conservé, prix dû à 0
        self.assertEqual(bilan["payments"][(101, self.comp_id)],
                         {"montant_paye": 15.0, "prix": 0.0})
        self.assertIn(101, bilan["students"])
        self.assertEqual(bilan["seasons"], ["2025-2026"])

    def test_annule_perdu_exclu_du_bilan(self):
        self.assertTrue(Repo.mark_cancelled(self.comp_id, 101, PAIEMENT_ANNULE_PERDU, "absence"))
        p = Repo.list_participants(self.comp_id)[0]
        self.assertFalse(p.selectionne)
        self.assertEqual(p.statut_paiement, PAIEMENT_ANNULE_PERDU)
        self.assertEqual(p.montant_paye, 15.0)

        bilan = Repo.get_bilan()
        self.assertNotIn((101, self.comp_id), bilan["participations"])
        self.assertNotIn((101, self.comp_id), bilan["payments"])

    def test_resync_helloasso_ne_pas_repayer_un_annule(self):
        Repo.mark_cancelled(self.comp_id, 101, PAIEMENT_ANNULE_REPORTE, "blessure")
        # Re-synchronisation HelloAsso (l'article payé est toujours validé) :
        # l'annulation explicite du coach ne doit pas être écrasée.
        self.assertFalse(Repo.apply_helloasso_payment(self.comp_id, 101, 15.0, order_ref="CMD-1"))
        p = Repo.list_participants(self.comp_id)[0]
        self.assertEqual(p.statut_paiement, PAIEMENT_ANNULE_REPORTE)
        self.assertFalse(p.selectionne)

    def test_reactivation_par_re_ajout(self):
        Repo.mark_cancelled(self.comp_id, 101, PAIEMENT_ANNULE_REPORTE, "blessure")
        Repo.add_participant(self.comp_id, 101, selectionne=True)
        p = Repo.list_participants(self.comp_id)[0]
        self.assertTrue(p.selectionne)
        self.assertEqual(p.statut_paiement, PAIEMENT_PAYE)
        self.assertEqual(p.montant_paye, 15.0)
        self.assertEqual(p.note_paiement, "blessure")


if __name__ == "__main__":
    unittest.main()
