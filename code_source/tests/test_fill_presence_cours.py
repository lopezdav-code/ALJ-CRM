import unittest
import sys
import os

# Ajustement du chemin pour importer les modules depuis 'src'
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from fill_presence_cours import normalize_string

class TestFillPresenceCours(unittest.TestCase):
    def test_normalize_string(self):
        """Vérifie le traitement de nettoyage robuste des accents et des casses."""
        self.assertEqual(normalize_string("César"), "cesar")
        self.assertEqual(normalize_string("  Chloé  "), "chloe")
        self.assertEqual(normalize_string("BEN MOUSSA"), "ben moussa")
        self.assertEqual(normalize_string(""), "")
        self.assertEqual(normalize_string(None), "")

if __name__ == "__main__":
    unittest.main()
