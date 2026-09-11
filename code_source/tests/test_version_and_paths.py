import os
import sys
import unittest

# Ajustement du chemin pour importer les modules depuis 'src'
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from paths import CODE_ROOT, DATA_ROOT, LEGACY_DB_PATH
from domain.constants import APP_VERSION


class TestVersionAndPaths(unittest.TestCase):
    """Fondations de la distribution : fichier VERSION (lu par l'updater) et
    séparation du dossier de données stables (data/) du code source."""

    def test_version_file_matches_app_version(self):
        """Le fichier VERSION (référence de l'updater) est aligné sur APP_VERSION."""
        version_path = os.path.join(CODE_ROOT, "VERSION")
        self.assertTrue(os.path.exists(version_path), "Fichier VERSION introuvable dans code_source/")
        with open(version_path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), APP_VERSION)

    def test_data_root_is_separate_from_code_root(self):
        """data/ (cache SQLite, fichiers utilisateurs) vit en dehors du code source :
        une mise à jour de l'app ne doit jamais toucher les données."""
        self.assertNotEqual(os.path.abspath(DATA_ROOT), os.path.abspath(CODE_ROOT))
        self.assertFalse(DATA_ROOT.startswith(CODE_ROOT + os.sep))

    def test_legacy_db_path_points_to_project_root(self):
        """L'ancien emplacement du cache (migration auto) est bien la racine projet."""
        self.assertEqual(os.path.basename(LEGACY_DB_PATH), "database.db")
        self.assertEqual(os.path.dirname(LEGACY_DB_PATH), os.path.dirname(CODE_ROOT))


if __name__ == "__main__":
    unittest.main()
