import os
import sys
import unittest
import shutil
import tempfile
from unittest.mock import patch

_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from infrastructure.sqlite_repository import SqliteRepository


def _ha_item(order_ref, last, first, status="Processed", amount=246.0, licence="", date="2026-08-20T10:00:00"):
    """Item HelloAsso au format canonique du pipeline (clés legacy)."""
    item = {
        "order_ref": order_ref,
        "order_date": date,
        "status": status,
        "tarif_name": "Loisir cours" if amount else "Liste d'attente",
        "amount": amount,
        "user_lastName": last,
        "user_firstName": first,
        "payer_lastName": last,
        "payer_firstName": "Payeur",
        "payer_email": f"{last.lower()}@test.fr",
        "is_modified": "Non",
        "commentaires_correctif": "",
    }
    if licence:
        item["champ_Numéro de Licence FFME (6 chiffres)"] = licence
    return item


class TestSyncPipeline(unittest.TestCase):
    """Phase 8 — Tests du cœur de synchronisation HelloAsso -> BDD (update_membership_excel)."""

    def setUp(self):
        self._original_db_path = SqliteRepository.get_db_path()
        self._tmpdir = tempfile.mkdtemp(prefix="alj_sync_test_")
        self._tmp_db = os.path.join(self._tmpdir, "database.db")
        SqliteRepository.set_db_path(self._tmp_db)
        SqliteRepository.setup_database()

        # Environnement Drive factice : base "partagée" avec un ID, téléchargement no-op
        # NB : get_file_hash n'est PAS mocké — le hash réel détermine l'upload conditionnel.
        from unittest.mock import MagicMock
        self._mock_upload = MagicMock()
        self._patches = [
            patch("create_excel.load_env_variables",
                  return_value={"GOOGLE_DRIVE_DB_ID": "TEST_DB_ID", "GOOGLE_DRIVE_FILE_ID": ""}),
            patch("create_excel.download_file_from_drive", return_value=True),
            patch("create_excel.upload_file_to_drive", self._mock_upload),
        ]
        for pt in self._patches:
            pt.start()
            self.addCleanup(pt.stop)

    def tearDown(self):
        SqliteRepository.set_db_path(self._original_db_path)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _run_sync(self, items):
        with patch("create_excel.get_helloasso_data", return_value=items):
            from create_excel import update_membership_excel
            return update_membership_excel()

    def test_nouvelle_adhesion_inseree_en_bdd(self):
        success, new_participants, _ = self._run_sync([_ha_item("ORD-1", "MARTIN", "Leo")])
        self.assertTrue(success)
        self.assertEqual(len(new_participants), 1)
        rows = SqliteRepository.load_direct_data(season_filter="2026-2027")
        match = next(r for r in rows if r["last_name"] == "MARTIN")
        self.assertEqual(match["order_ref"], "ORD-1")
        self.assertEqual(match["is_modified"], "Oui (Ajouté)")
        self.assertEqual(match["payer_email"], "martin@test.fr")
        # La base a change : televersement Drive attendu
        self._mock_upload.assert_called()

    def test_dedup_order_ref_nom_prenom_deja_present(self):
        item = _ha_item("ORD-2", "DUBOIS", "Claire")
        SqliteRepository.upsert_members([dict(item)])
        success, new_participants, msg = self._run_sync([dict(item)])
        self.assertTrue(success)
        self.assertEqual(len(new_participants), 0)
        self.assertIn("déjà à jour", msg)
        self._mock_upload.assert_not_called()

    def test_dedup_par_licence_ffme(self):
        SqliteRepository.upsert_members([_ha_item("ORD-3A", "BERNI", "Paul", licence="123456")])
        # Meme licence, commande differente : doit etre ignore (controle 1)
        success, new_participants, _ = self._run_sync([_ha_item("ORD-3B", "BERNI", "Paul", licence="123456")])
        self.assertTrue(success)
        self.assertEqual(len(new_participants), 0)

    def test_priorite_statut_processed_masque_canceled(self):
        SqliteRepository.upsert_members([_ha_item("ORD-4A", "ROUX", "Eva", status="Processed", amount=246.0)])
        # Commande annulee en liste d'attente pour le meme adherent : ignoree (controle 0)
        success, new_participants, _ = self._run_sync(
            [_ha_item("ORD-4B", "ROUX", "Eva", status="Canceled", amount=0.0)])
        self.assertTrue(success)
        self.assertEqual(len(new_participants), 0)
        rows = [r for r in SqliteRepository.load_direct_data(season_filter="2026-2027") if r["last_name"] == "ROUX"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "Processed")

    def test_famille_multi_adherents_meme_commande(self):
        success, new_participants, _ = self._run_sync([
            _ha_item("ORD-FAM", "LEGRAND", "Mere"),
            _ha_item("ORD-FAM", "LEGRAND", "Fils"),
        ])
        self.assertTrue(success)
        self.assertEqual(len(new_participants), 2)
        rows = [r for r in SqliteRepository.load_direct_data(season_filter="2026-2027") if r["last_name"] == "LEGRAND"]
        self.assertEqual(len(rows), 2)

    def test_api_helloasso_vide_interrompt_le_pipeline(self):
        success, new_participants, msg = self._run_sync([])
        self.assertFalse(success)
        self.assertEqual(len(new_participants), 0)
        self.assertIn("Impossible de charger", msg)

    def test_accentues_normalises_pas_de_doublon(self):
        SqliteRepository.upsert_members([_ha_item("ORD-5A", "GONZALEZ", "Inès", licence="111222")])
        # Meme personne avec accents different sur une nouvelle commande : licence deja presente
        success, new_participants, _ = self._run_sync([_ha_item("ORD-5B", "GONZÁLEZ", "Inès", licence="111222")])
        self.assertTrue(success)
        self.assertEqual(len(new_participants), 0)


if __name__ == "__main__":
    unittest.main()
