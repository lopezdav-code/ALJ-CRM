"""Tests du changement de groupe (tarif) d'un adhérent : repository + pop-up radio."""
import os
import sys
import unittest

# Ajustement du chemin d'import
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from infrastructure.sqlite_repository import SqliteRepository

try:
    from PySide6.QtWidgets import QApplication, QDialog
    from domain.models import Member
    from presentation.pages.members import TarifEditDialog
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False

TEST_MEMBER = {
    "order_ref": "88888",
    "order_date": "2026-09-01T10:00:00",
    "status": "Validated",
    "tarif_name": "Loisir - Enfants 2016-2018",
    "amount": 150.0,
    "user_lastName": "MARTIN",
    "user_firstName": "Léo",
    "payer_lastName": "MARTIN",
    "payer_firstName": "Claire",
    "payer_email": "claire.martin@test.com",
    "champ_Date de naissance de l'adhérent": "2017-03-10",
    "is_modified": "Non",
    "commentaires_correctif": "",
}


class TestTarifUpdateRepository(unittest.TestCase):

    def setUp(self):
        self.original_db_path = SqliteRepository.get_db_path()
        self.test_db_path = os.path.join(_test_dir, "test_tarif_database.db")
        SqliteRepository.set_db_path(self.test_db_path)
        SqliteRepository._database_setup_done = False
        SqliteRepository.setup_database()

    def tearDown(self):
        SqliteRepository.set_db_path(self.original_db_path)
        SqliteRepository._database_setup_done = False
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except Exception:
                pass

    def _seed(self, tarifs):
        for i, tarif in enumerate(tarifs):
            member = dict(TEST_MEMBER)
            member["order_ref"] = f"8888{i}"
            member["tarif_name"] = tarif
            SqliteRepository.upsert_members([member])

    def test_get_season_tarifs(self):
        self._seed(["Loisir - Enfants 2016-2018", "Adultes autonomes", "Adultes autonomes"])
        tarifs = SqliteRepository.get_season_tarifs("2026-2027")
        self.assertEqual(tarifs, sorted(set(tarifs)))
        self.assertIn("Adultes autonomes", tarifs)
        self.assertIn("Loisir - Enfants 2016-2018", tarifs)

    def test_update_member_tarif(self):
        self._seed(["Loisir - Enfants 2016-2018", "Loisir - Collège"])
        ok, err = SqliteRepository.update_member_tarif(
            "88880", "MARTIN", "Léo", "Loisir - Collège"
        )
        self.assertTrue(ok, err)
        loaded = [m for m in SqliteRepository.load_direct_data() if m["order_ref"] == "88880"]
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["tarif_name"], "Loisir - Collège")
        self.assertEqual(loaded[0]["is_modified"], "Oui")

    def test_update_member_tarif_unknown_member(self):
        self._seed(["Loisir - Enfants 2016-2018"])
        ok, err = SqliteRepository.update_member_tarif("00000", "INCONNU", "Xavier", "Adultes autonomes")
        self.assertFalse(ok)
        self.assertTrue(err)

    def test_update_member_tarif_empty(self):
        self._seed(["Loisir - Enfants 2016-2018"])
        ok, err = SqliteRepository.update_member_tarif("88880", "MARTIN", "Léo", "   ")
        self.assertFalse(ok)


@unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
class TestTarifEditDialog(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_member(self, tarif="Loisir - Enfants 2016-2018"):
        return Member(
            order_ref="88880", order_date="2026-09-01", status="Validated",
            tarif_name=tarif, amount=150.0, user_last_name="MARTIN",
            user_first_name="Léo", payer_first_name="Claire", payer_last_name="MARTIN",
            payer_email="claire.martin@test.com"
        )

    def test_radio_list_and_preselection(self):
        tarifs = ["Adultes autonomes", "Loisir - Collège", "Loisir - Enfants 2016-2018"]
        dialog = TarifEditDialog(self._make_member(), tarifs)
        self.assertEqual(len(dialog.radio_buttons), 3)
        checked = [rb.text() for rb in dialog.radio_buttons if rb.isChecked()]
        self.assertEqual(checked, ["Loisir - Enfants 2016-2018"])

    def test_get_selected_tarif(self):
        dialog = TarifEditDialog(self._make_member(tarif="Adultes autonomes"),
                                 ["Adultes autonomes", "Loisir - Collège"])
        # Simuler la sélection du deuxième tarif
        dialog.radio_buttons[1].setChecked(True)
        dialog.accept_selection()
        self.assertEqual(dialog.get_selected_tarif(), "Loisir - Collège")

    def test_same_tarif_closes_without_validation(self):
        dialog = TarifEditDialog(self._make_member(tarif="Adultes autonomes"),
                                 ["Adultes autonomes", "Loisir - Collège"])
        # Garder le tarif actuel sélectionné : la validation doit refuser (dialog reste ouvert)
        dialog.radio_buttons[0].setChecked(True)
        dialog.accept_selection()
        self.assertEqual(dialog.result(), QDialog.Rejected)


if __name__ == "__main__":
    unittest.main()
