import unittest
import os
import sys

# Ajustement du chemin pour importer les modules depuis 'src'
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from presence_sheet_generator import clean_filename, format_encadrants

class TestPresenceSheetGenerator(unittest.TestCase):
    def test_clean_filename(self):
        """Vérifie le nettoyage des noms de fichiers de présence."""
        self.assertEqual(clean_filename("Adultes autonomes"), "Adultes_autonomes")
        self.assertEqual(clean_filename("Loisir lycée / jeunes"), "Loisir_lycée_jeunes")
        self.assertEqual(clean_filename("Compétition - U15-U19"), "Compétition_-_U15-U19")

    def test_format_encadrants(self):
        """Vérifie le formatage des encadrants séparé en Prénom et Nom."""
        self.assertEqual(format_encadrants([]), ("-", "-"))
        
        last, first = format_encadrants(["Camille DIDIER"])
        self.assertEqual(last, "DIDIER")
        self.assertEqual(first, "Camille")
        
        last, first = format_encadrants(["Antoine GAUTHIER", "Rodolphe JULLIEN-MOUTELON"])
        self.assertEqual(last, "GAUTHIER / JULLIEN-MOUTELON")
        self.assertEqual(first, "Antoine / Rodolphe")

if __name__ == "__main__":
    unittest.main()
