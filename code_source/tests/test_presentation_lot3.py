import os
import sys
import unittest

# S'assurer de charger src dans sys.path pour les tests
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

try:
    from PySide6.QtWidgets import QApplication
    from presentation.main_window import MainWindow
    from presentation.pages.dashboard import DashboardPage
    from presentation.pages.members import MembersPage
    from presentation.pages.documents import DocumentsPage
    from presentation.pages.communications import CommunicationsPage
    from presentation.pages.exports import ExportsPage
    from presentation.pages.ffme import ImportDataPage
    from presentation.pages.gmail_contact import GmailContactPage
    from presentation.pages.groups import GroupsPage
    from presentation.pages.reports import ReportsPage
    from presentation.pages.settings import SettingsPage
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False

class TestPresentationLot3(unittest.TestCase):

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
    def test_pages_instantiation(self):
        """Vérifie que tous les widgets de pages s'instancient sans erreurs de dépendances."""
        # Créer QApplication requis pour instancier des widgets
        app = QApplication.instance() or QApplication([])
        
        dashboard = DashboardPage()
        members = MembersPage()
        documents = DocumentsPage()
        communications = CommunicationsPage()
        exports = ExportsPage()
        ffme = ImportDataPage()
        contacts = GmailContactPage()
        groups = GroupsPage()
        reports = ReportsPage()
        settings = SettingsPage()
        
        self.assertIsNotNone(dashboard)
        self.assertIsNotNone(members)
        self.assertIsNotNone(documents)
        self.assertIsNotNone(communications)
        self.assertIsNotNone(exports)
        self.assertIsNotNone(ffme)
        self.assertIsNotNone(contacts)
        self.assertIsNotNone(groups)
        self.assertIsNotNone(reports)
        self.assertIsNotNone(settings)

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
    def test_main_window_structure(self):
        """Vérifie que la MainWindow s'instancie correctement avec sa structure de widgets."""
        app = QApplication.instance() or QApplication([])
        
        win = MainWindow()
        self.assertIsNotNone(win)
        self.assertEqual(win.stacked_widget.count(), 11)
        self.assertEqual(len(win.nav_buttons), 11)

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
    def test_main_window_drive_status_email(self):
        """Vérifie que l'e-mail du compte Google s'affiche et s'actualise dynamiquement dans l'en-tête."""
        from unittest.mock import patch
        app = QApplication.instance() or QApplication([])
        
        with patch("infrastructure.secret_store.SecretStore.get_secret", return_value="test_account@gmail.com"):
            win = MainWindow()
            self.assertIn("test_account@gmail.com", win.drive_status.text())
            
        with patch("infrastructure.secret_store.SecretStore.get_secret", return_value="updated_account@gmail.com"):
            win.on_nav_changed(1)
            self.assertIn("updated_account@gmail.com", win.drive_status.text())

    @unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
    def test_communications_popup_filters_default(self):
        """Vérifie les pop-up tarifs/statuts de l'onglet Communications :
        défaut = tous les tarifs sauf la liste d'attente, tous les statuts sauf Annulé."""
        app = QApplication.instance() or QApplication([])
        from domain.models import Member

        def make_member(ref, status, tarif, email):
            return Member(
                order_ref=ref, order_date="2026-08-01", status=status, amount=1.0,
                user_last_name=f"Nom{ref}", user_first_name="Prenom",
                payer_first_name="Jean", payer_last_name="Dupont", payer_email=email,
                tarif_name=tarif
            )

        comm = CommunicationsPage()
        m1 = make_member("1", "Validated", "Cours Adultes débutants", "a@test.com")
        m2 = make_member("2", "Canceled", "Loisir enfants nés en 2016, 2017, 2018 - mercredi 10h30", "c@test.com")
        m3 = make_member("3", "Terminé", "Liste d'attente cours", "e@test.com")

        comm.load_members(members_list=[m1, m2, m3])

        # Sélections par défaut : tarifs hors liste d'attente, statuts hors Annulé
        self.assertEqual(
            comm.selected_tarifs,
            {"Cours Adultes débutants", "Loisir enfants nés en 2016, 2017, 2018 - mercredi 10h30"}
        )
        self.assertEqual(comm.selected_statuses, {"Validé", "Terminé"})
        self.assertEqual(comm.tarif_filter.text(), "Tous sauf liste d'attente ▾")
        self.assertEqual(comm.status_filter.text(), "Tous sauf annulés ▾")

        # L'annulé et la liste d'attente sont masqués de la liste des destinataires
        comm.on_filters_changed()
        visible = [comm.list_widget.item(i).text()
                   for i in range(comm.list_widget.count())
                   if not comm.list_widget.item(i).isHidden()]
        self.assertEqual(len(visible), 1)
        self.assertIn("a@test.com", visible[0])

if __name__ == "__main__":
    unittest.main()
