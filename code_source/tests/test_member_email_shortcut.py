import os
import sys
import unittest

# Ajustement du chemin pour importer les modules depuis 'src'
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from infrastructure.sqlite_repository import SqliteRepository

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QStackedWidget, QWidget
    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


def make_member(last_name="MARTIN", first_name="Paul", order_ref="12345"):
    """Construit un adhérent de test."""
    from domain.models import Member
    return Member(
        order_ref=order_ref, order_date="2026-08-01", status="Validated",
        tarif_name="Adulte", amount=246.0, user_last_name=last_name,
        user_first_name=first_name, payer_first_name="Jean", payer_last_name=last_name,
        payer_email=f"{first_name.lower()}.{last_name.lower()}@test.com"
    )


@unittest.skipIf(not PYSIDE6_AVAILABLE, "PySide6 n'est pas disponible pour tester l'IHM")
class TestMemberEmailShortcut(unittest.TestCase):
    """Bouton ✉️ de la fiche adhérent : redirection vers Communication filtrée sur la personne."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.original_db_path = SqliteRepository.get_db_path()
        self.test_db_path = os.path.join(_test_dir, "test_email_shortcut.db")
        SqliteRepository.set_db_path(self.test_db_path)

    def tearDown(self):
        SqliteRepository.set_db_path(self.original_db_path)
        for suffix in ("", "-wal", "-shm"):
            p = self.test_db_path + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def test_detail_panel_emits_email_request(self):
        """Le bouton ✉️ de la fiche émet le signal avec l'adhérent courant."""
        from presentation.components.member_detail_panel import MemberDetailPanel
        member = make_member()

        panel = MemberDetailPanel()
        captured = []
        panel.email_requested.connect(lambda m: captured.append(m))

        panel.set_member(member)
        panel.email_btn.click()

        self.assertEqual(len(captured), 1)
        self.assertIs(captured[0], member)

    def test_members_page_bubbles_email_request(self):
        """La page Adhérents remonte la demande ✉️ de la fiche vers la fenêtre principale."""
        from presentation.pages.members import MembersPage
        member = make_member()

        page = MembersPage()
        captured = []
        page.email_requested.connect(lambda m: captured.append(m))

        page.detail_panel.set_member(member)
        page.detail_panel.email_btn.click()

        self.assertEqual(len(captured), 1)
        self.assertIs(captured[0], member)

    def test_communications_focus_on_member_filters_list(self):
        """focus_on_member remplit la recherche avec le nom et ne laisse visible que la personne."""
        from presentation.pages.communications import CommunicationsPage
        from infrastructure.sqlite_repository import SqliteRepository as Repo

        base_member = {
            "order_ref": "99999",
            "order_date": "2026-08-16T14:30:00",
            "status": "Validated",
            "tarif_name": "Adultes autonomes",
            "amount": 150.0,
            "user_lastName": "DUPONT",
            "user_firstName": "Jean",
            "payer_lastName": "DUPONT",
            "payer_firstName": "Jean",
            "payer_email": "jean.dupont@test.com",
        }
        martin = dict(base_member, order_ref="88888", user_lastName="MARTIN", user_firstName="Paul",
                      payer_email="paul.martin@test.com")
        Repo.setup_database()
        Repo.upsert_members([base_member, martin])

        page = CommunicationsPage()
        page.load_members()
        self.assertEqual(page.list_widget.count(), 2)

        target = make_member(last_name="MARTIN", first_name="Paul", order_ref="88888")
        page.focus_on_member(target)

        self.assertEqual(page.search_input.text(), "MARTIN")
        visible_items = []
        for i in range(page.list_widget.count()):
            item = page.list_widget.item(i)
            if not item.isHidden():
                visible_items.append(item.data(Qt.UserRole))
        self.assertEqual(len(visible_items), 1)
        self.assertEqual(visible_items[0].user_last_name, "MARTIN")

    def test_main_window_handler_switches_to_communications(self):
        """Le handler de la fenêtre principale bascule sur Communication, coche le bon
        onglet et pré-filtre la recherche sur l'adhérent."""
        from presentation.main_window import MainWindow
        from presentation.pages.members import MembersPage
        from presentation.pages.communications import CommunicationsPage

        stack = QStackedWidget()
        members_page = MembersPage()
        comm_page = CommunicationsPage()
        stack.addWidget(members_page)  # Index 0 (Adhérents)
        stack.addWidget(QWidget())     # Index 1 (Attestations)
        stack.addWidget(comm_page)     # Index 2 (Communications)

        nav = []
        for _ in range(3):
            btn = QPushButton()
            btn.setCheckable(True)
            nav.append(btn)

        class FakeWindow:
            pass

        fake = FakeWindow()
        fake.stacked_widget = stack
        fake.nav_buttons = nav
        fake.drive_status = QLabel()
        fake.nav_calls = []

        def fake_on_nav_changed(index, force_reload=False):
            # Déléguer à la vraie méthode pour vérifier le changement réel de page
            MainWindow.on_nav_changed(fake, index, force_reload=force_reload)
            fake.nav_calls.append(index)

        fake.on_nav_changed = fake_on_nav_changed

        member = make_member(last_name="DUPONT", first_name="Jean", order_ref="99999")
        MainWindow.open_communications_for_member(fake, member)

        self.assertEqual(stack.currentIndex(), 2)
        self.assertTrue(nav[2].isChecked())
        self.assertFalse(nav[0].isChecked())
        self.assertEqual(fake.nav_calls, [2])
        self.assertEqual(comm_page.search_input.text(), "DUPONT")


if __name__ == "__main__":
    unittest.main()
