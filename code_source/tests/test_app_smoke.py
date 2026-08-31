import os
import sys
import unittest
import shutil
import sqlite3
import tempfile
import pathlib

# Rendu headless : doit être défini avant tout import PySide6
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

ROOT_PROJET = os.path.dirname(os.path.dirname(_test_dir))


class TestAppSmoke(unittest.TestCase):
    """
    Phase 7 — Smoke test applicatif : instancie la MainWindow complète (11 pages)
    sur un snapshot de la base réelle, sans afficher de fenêtre ni toucher à la base live.
    """

    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication  # noqa: F401
            from presentation.main_window import MainWindow  # noqa: F401
            cls.PYSIDE6_AVAILABLE = True
        except ImportError:
            cls.PYSIDE6_AVAILABLE = False
            return

        from infrastructure.sqlite_repository import SqliteRepository
        cls._SqliteRepository = SqliteRepository

        cls._tmpdir = tempfile.mkdtemp(prefix="alj_app_smoke_test_")
        cls._tmp_db = os.path.join(cls._tmpdir, "database.db")
        cls._original_db_path = SqliteRepository.get_db_path()

        db_live = os.path.join(ROOT_PROJET, "database.db")
        if os.path.exists(db_live):
            # Snapshot cohérent de la base réelle (API backup : inclut le WAL)
            uri = f"{pathlib.Path(db_live).as_uri()}?mode=ro"
            src = sqlite3.connect(uri, uri=True)
            dst = sqlite3.connect(cls._tmp_db)
            src.backup(dst)
            dst.close()
            src.close()
        else:
            # CI / poste neuf : base v2 fraîche
            SqliteRepository.set_db_path(cls._tmp_db)
            SqliteRepository.setup_database()

    @classmethod
    def tearDownClass(cls):
        if not cls.PYSIDE6_AVAILABLE:
            return
        cls._SqliteRepository.set_db_path(cls._original_db_path)
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_main_window_boots_with_real_schema(self):
        if not self.PYSIDE6_AVAILABLE:
            self.skipTest("PySide6 non disponible")
        from PySide6.QtWidgets import QApplication
        from presentation.main_window import MainWindow

        self._SqliteRepository.set_db_path(self._tmp_db)
        app = QApplication.instance() or QApplication([])
        win = MainWindow()
        try:
            self.assertIsNotNone(win)
            # 11 pages attendues (Adhérents .. Logs)
            self.assertEqual(win.stacked_widget.count(), 11)
            self.assertEqual(len(win.nav_buttons), 11)
        finally:
            win.close()


if __name__ == "__main__":
    unittest.main()
