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
        m4 = Member(
            order_ref="103", order_date="2026-08-01", status="Validated", 
            amount=246.0, payer_first_name="Jean", payer_last_name="Dupont", payer_email="test@test.com",
            user_last_name="G", user_first_name="H", tarif_name="Liste d'attente cours"
        )
        
        page.members_list = [m1, m2, m3, m4]
        
        # 3. Tester le regroupement des sous-catégories par type (pour la pop-up)
        # 'Liste d'attente cours' doit être isolée dans son propre sous-groupe, en premier
        groups = page.get_tarif_groups()
        self.assertEqual(groups[0], ("Liste d'attente", ["Liste d'attente cours"]))
        groups_dict = dict(groups)
        self.assertEqual(groups_dict["Séance autonome"], ["Adultes autonomes"])
        self.assertEqual(groups_dict["Compétition"], ["Compétition U11 U13"])
        self.assertEqual(groups_dict["Cours"], ["Cours Adultes débutants"])

        # 4. Tester le filtrage par sélection de sous-catégories (pop-up à cases à cocher)
        page.tarif_type_filter.setCurrentText("Tous les types")
        page.selected_sub_tarifs = {"Adultes autonomes", "Cours Adultes débutants"}
        page.on_filters_changed()
        tarifs_shown = [m.tarif_name for m in page.base_model.members]
        self.assertIn("Adultes autonomes", tarifs_shown)
        self.assertIn("Cours Adultes débutants", tarifs_shown)
        self.assertNotIn("Compétition U11 U13", tarifs_shown)

        # 5. Le changement de type retire les sous-catégories hors type (élagage de la sélection)
        page.tarif_type_filter.setCurrentText("Séance autonome")
        self.assertEqual(page.selected_sub_tarifs, {"Adultes autonomes"})

        # 6. Sélection par défaut : tout est coché sauf 'Liste d'attente cours' (désélectionnée)
        page.tarif_type_filter.setCurrentText("Tous les types")
        page.notify_members_reloaded()
        self.assertEqual(
            page.selected_sub_tarifs,
            {"Adultes autonomes", "Compétition U11 U13", "Cours Adultes débutants"}
        )
        self.assertEqual(page.tarif_sub_filter.text(), "Toutes sauf liste d'attente ▾")
        tarifs_shown = [m.tarif_name for m in page.base_model.members]
        self.assertNotIn("Liste d'attente cours", tarifs_shown)

        # 7. Le filtre de statuts est dynamique : seuls les statuts présents sont listés
        page.refresh_status_filter()
        status_items = [page.status_filter.itemText(i) for i in range(page.status_filter.count())]
        self.assertIn("Tous les statuts", status_items)
        self.assertIn("Validé", status_items)  # "Validated" normalisé en "Validé"
        self.assertNotIn("Annulé", status_items)  # Aucun adhérent annulé dans la liste
        self.assertNotIn("Traité", status_items)  # Aucun adhérent traité dans la liste

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
    def test_date_filter_with_timezone_dates(self):
        """Régression : le filtre 'Inscrit après le' ne doit pas exclure les adhérents
        dont la date d'inscription contient un fuseau horaire ('...+02:00')."""
        app = QApplication.instance() or QApplication([])
        from PySide6.QtCore import QDate
        from presentation.pages.members import parse_order_date

        # Le parseur gère ISO avec fuseau, ISO simple et JJ/MM/AAAA
        self.assertEqual(str(parse_order_date("2026-09-03T17:38:18.2040937+02:00")), "2026-09-03")
        self.assertEqual(str(parse_order_date("2025-09-01")), "2025-09-01")
        self.assertEqual(str(parse_order_date("01/09/2026")), "2026-09-01")
        self.assertIsNone(parse_order_date(""))
        self.assertIsNone(parse_order_date("n'importe quoi"))

        page = MembersPage()
        kw = dict(order_date="2026-09-03T17:38:18.2040937+02:00", status="Validated", amount=1.0,
                  payer_first_name="J", payer_last_name="D", payer_email="t@t.com")
        m_tz = Member(order_ref="1", user_last_name="A", user_first_name="B", tarif_name="T1", **kw)
        m_old = Member(order_ref="2", user_last_name="C", user_first_name="D", tarif_name="T2",
                       order_date="2025-09-01", status="Validated", amount=1.0,
                       payer_first_name="J", payer_last_name="D", payer_email="t2@t.com")

        page.members_list = [m_tz, m_old]
        page.date_checkbox.setChecked(True)
        page.date_edit.setDate(QDate(2026, 7, 1))
        page.on_filters_changed()
        refs = [m.order_ref for m in page.base_model.members]
        # La date avec fuseau (03/09/2026) doit être INCLUSE, l'ancienne (01/09/2025) exclue
        self.assertIn("1", refs)
        self.assertNotIn("2", refs)

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
    def test_default_sort_by_registration_date_desc(self):
        """Vérifie que le tableau des adhérents est trié par défaut par date
        d'inscription décroissante (la plus récente en premier)."""
        app = QApplication.instance() or QApplication([])

        page = MembersPage()
        m_old = Member(order_ref="1", user_last_name="Ancien", user_first_name="A", tarif_name="T1",
                       order_date="2025-09-01", status="Validated", amount=1.0,
                       payer_first_name="J", payer_last_name="D", payer_email="a@t.com")
        m_new = Member(order_ref="2", user_last_name="Recent", user_first_name="B", tarif_name="T2",
                       order_date="2026-09-03T17:38:18.2040937+02:00", status="Validated", amount=1.0,
                       payer_first_name="J", payer_last_name="D", payer_email="b@t.com")

        page.members_list = [m_old, m_new]
        page.notify_members_reloaded()

        date_col = next(i for i, c in enumerate(MemberTableModel.COLUMNS) if c[1] == "order_date")
        first_row_src = page.proxy_model.mapToSource(page.proxy_model.index(0, date_col)).row()
        self.assertEqual(page.base_model.members[first_row_src].order_ref, "2")
        second_row_src = page.proxy_model.mapToSource(page.proxy_model.index(1, date_col)).row()
        self.assertEqual(page.base_model.members[second_row_src].order_ref, "1")

if __name__ == "__main__":
    from PySide6.QtCore import Qt # Pour utiliser Qt.SortOrder dans l'exécution directe
    unittest.main()
