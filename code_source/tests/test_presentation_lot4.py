import os
import sys
import unittest

# S'assurer de charger src dans sys.path pour les tests
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from domain.models import Member

try:
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from presentation.components.member_table_model import MemberTableModel
    from presentation.components.member_detail_panel import MemberDetailPanel
    from presentation.pages.members import MembersPage
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False
    MemberTableModel = None

class TestPresentationLot4(unittest.TestCase):

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
    def test_table_model_behavior(self):
        """Vérifie le comportement de tri, de colonnes et de comptage du MemberTableModel."""
        m1 = Member(
            order_ref="100", order_date="2026-08-01", status="Validated", 
            tarif_name="Adulte", amount=246.0, user_last_name="Zebra", 
            user_first_name="Zack", payer_first_name="Jean", payer_last_name="Zebra", 
            payer_email="test@test.com"
        )
        m2 = Member(
            order_ref="101", order_date="2026-08-02", status="Validated", 
            tarif_name="Enfant", amount=150.0, user_last_name="Apple", 
            user_first_name="Andy", payer_first_name="Jean", payer_last_name="Apple", 
            payer_email="test@test.com"
        )

        model = MemberTableModel([m1, m2])
        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(model.columnCount(), 9)

        # Vérifier le tri (colonne 2 = user_last_name)
        # Ordre croissant : Apple doit passer devant Zebra
        model.sort(2, Qt.SortOrder.AscendingOrder)
        self.assertEqual(model.members[0].user_last_name, "Apple")
        self.assertEqual(model.members[1].user_last_name, "Zebra")

        # Ordre décroissant : Zebra repasse devant Apple
        model.sort(2, Qt.SortOrder.DescendingOrder)
        self.assertEqual(model.members[0].user_last_name, "Zebra")
        self.assertEqual(model.members[1].user_last_name, "Apple")

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
    def test_detail_panel_and_page(self):
        """Vérifie que la fiche adhérent et la page s'instancient et s'actualisent sans erreur."""
        app = QApplication.instance() or QApplication([])
        
        panel = MemberDetailPanel()
        self.assertIsNotNone(panel)
        
        m = Member(
            order_ref="100", order_date="2026-08-01", status="Validated", 
            tarif_name="Adulte", amount=246.0, user_last_name="Dupont", 
            user_first_name="Jean", payer_first_name="Jean", payer_last_name="Dupont", 
            payer_email="test@test.com"
        )
        panel.set_member(m)
        self.assertEqual(panel.title_label.text(), "Dupont Jean")

        page = MembersPage()
        self.assertIsNotNone(page)
        self.assertFalse(page.detail_panel.isVisible())

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
    def test_tariff_filtering_logic(self):
        """Vérifie la catégorisation des tarifs et le fonctionnement des nouveaux sous-filtres."""
        app = QApplication.instance() or QApplication([])
        
        page = MembersPage()
        self.assertIsNotNone(page)
        
        # 1. Tester get_tariff_category
        self.assertEqual(page.get_tariff_category("Adultes autonomes"), "Séance autonome")
        self.assertEqual(page.get_tariff_category("Jeunes Adultes autonomes - nés entre 2001 et 2008"), "Séance autonome")
        self.assertEqual(page.get_tariff_category("Compétition U11 U13"), "Compétition")
        self.assertEqual(page.get_tariff_category("Cours Adultes débutants"), "Cours")
        self.assertEqual(page.get_tariff_category("Loisir collège"), "Cours")
        self.assertEqual(page.get_tariff_category("Perfectionnement U11"), "Cours")
        self.assertEqual(page.get_tariff_category("Inconnu"), "Autre")
        
        # 2. Simuler des membres de différentes catégories
        m1 = Member(
            order_ref="100", order_date="2026-08-01", status="Validated", 
            amount=246.0, payer_first_name="Jean", payer_last_name="Dupont", payer_email="test@test.com",
            user_last_name="A", user_first_name="B", tarif_name="Adultes autonomes"
        )
        m2 = Member(
            order_ref="101", order_date="2026-08-01", status="Validated", 
            amount=246.0, payer_first_name="Jean", payer_last_name="Dupont", payer_email="test@test.com",
            user_last_name="C", user_first_name="D", tarif_name="Compétition U11 U13"
        )
        m3 = Member(
            order_ref="102", order_date="2026-08-01", status="Validated", 
            amount=246.0, payer_first_name="Jean", payer_last_name="Dupont", payer_email="test@test.com",
            user_last_name="E", user_first_name="F", tarif_name="Cours Adultes débutants"
        )
        
        page.members_list = [m1, m2, m3]
        
        # 3. Tester le changement de catégorie de tarif
        # Sélectionner "Séance autonome"
        page.tarif_type_filter.setCurrentText("Séance autonome")
        # Cela doit mettre à jour les sous-catégories disponibles
        sub_items = [page.tarif_sub_filter.itemText(i) for i in range(page.tarif_sub_filter.count())]
        self.assertIn("Toutes les sous-catégories", sub_items)
        self.assertIn("Adultes autonomes", sub_items)
        self.assertNotIn("Compétition U11 U13", sub_items)
        self.assertNotIn("Cours Adultes débutants", sub_items)

if __name__ == "__main__":
    from PySide6.QtCore import Qt # Pour utiliser Qt.SortOrder dans l'exécution directe
    unittest.main()
