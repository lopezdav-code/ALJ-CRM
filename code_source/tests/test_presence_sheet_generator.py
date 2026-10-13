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

    def test_presence_api_config(self):
        """Vérifie que /api/presence/config renvoie la structure attendue pour l'IHM."""
        from fastapi.testclient import TestClient
        from server import app
        client = TestClient(app, base_url="http://localhost")
        resp = client.get("/api/presence/config")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("autonome", data)
        self.assertIn("cours", data)
        self.assertIn("default_dates", data)

    def test_presence_api_export_autonome(self):
        """Vérifie que /api/presence/export génère et télécharge une feuille Excel pour les autonomes."""
        from fastapi.testclient import TestClient
        from server import app
        client = TestClient(app, base_url="http://localhost")
        resp = client.post("/api/presence/export", json={"variant": "autonome", "show_health_col": True})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("attachment", resp.headers.get("content-disposition", ""))
        self.assertGreater(len(resp.content), 1000)

    def test_presence_api_export_cours(self):
        """Vérifie que /api/presence/export génère et télécharge les feuilles des cours (same_sheet=True)."""
        from fastapi.testclient import TestClient
        from server import app
        client = TestClient(app, base_url="http://localhost")
        resp = client.post("/api/presence/export", json={"variant": "cours", "same_sheet": True})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("attachment", resp.headers.get("content-disposition", ""))
        self.assertGreater(len(resp.content), 1000)

if __name__ == "__main__":
    unittest.main()
