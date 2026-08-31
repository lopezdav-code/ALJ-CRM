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
    from presentation.pages.ffme import FFMEPage
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
        ffme = FFMEPage()
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
        self.assertEqual(win.stacked_widget.count(), 10)
        self.assertEqual(len(win.nav_buttons), 10)

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

if __name__ == "__main__":
    unittest.main()
