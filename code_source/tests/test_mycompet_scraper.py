import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Ajuster le chemin d'import
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))
from mycompet_scraper import scrape_mycompet

class TestMyCompetScraper(unittest.TestCase):
    @patch("requests.get")
    def test_scrape_mycompet_success(self, mock_get):
        # Créer des réponses fictives pour les 3 disciplines
        mock_response_1 = MagicMock()
        mock_response_1.status_code = 200
        mock_response_1.text = """
        <html>
            <body>
                <div>
                    <h2>Classement National Escalade - BLOC</h2>
                    <table>
                        <tr>
                            <th>Rang</th>
                            <th>Nom</th>
                            <th>Club</th>
                        </tr>
                        <tr>
                            <td>1</td>
                            <td>DUPONT Jean</td>
                            <td>ALJ Escalade</td>
                        </tr>
                        <tr>
                            <td>2</td>
                            <td>MARTIN Pierre</td>
                            <td>Club Lyon</td>
                        </tr>
                    </table>
                </div>
            </body>
        </html>
        """
        
        mock_response_2 = MagicMock()
        mock_response_2.status_code = 200
        mock_response_2.text = """
        <html>
            <body>
                <div>
                    <h2>Classement National Escalade - VITESSE</h2>
                    <table>
                        <tr>
                            <th>Rang</th>
                            <th>Nom</th>
                            <th>Club</th>
                        </tr>
                        <tr>
                            <td>1</td>
                            <td>DURAND Alice</td>
                            <td>ALJ Escalade</td>
                        </tr>
                        <tr>
                            <td>2</td>
                            <td>PETIT Sophie</td>
                            <td>Club Paris</td>
                        </tr>
                    </table>
                </div>
            </body>
        </html>
        """

        mock_response_3 = MagicMock()
        mock_response_3.status_code = 200
        mock_response_3.text = """
        <html>
            <body>
                <div>
                    <h2>Classement National Escalade - DIFFICULTÉ</h2>
                    <table>
                        <tr>
                            <th>Rang</th>
                            <th>Nom</th>
                            <th>Club</th>
                        </tr>
                        <tr>
                            <td>1</td>
                            <td>GARCIA Lucas</td>
                            <td>ALJ Escalade</td>
                        </tr>
                        <tr>
                            <td>2</td>
                            <td>LOPEZ David</td>
                            <td>ALJ Escalade</td>
                        </tr>
                    </table>
                </div>
            </body>
        </html>
        """

        # Configurer le mock pour retourner les 3 pages successivement
        mock_get.side_effects = [mock_response_1, mock_response_2, mock_response_3]
        mock_get.side_effect = [mock_response_1, mock_response_2, mock_response_3]

        # Lancer le scraping
        progress_calls = []
        def progress_cb(msg, pct):
            progress_calls.append((msg, pct))

        with patch("paths.ROOT_DIR", os.path.dirname(__file__)):
            excel_path = scrape_mycompet(progress_callback=progress_cb)
            
            # Vérifications
            self.assertTrue(os.path.exists(excel_path))
            self.assertTrue(excel_path.endswith("MyCompet.xlsx"))
            
            # Vérifier que progress a été appelé
            self.assertTrue(len(progress_calls) > 0)
            
            # Nettoyer
            if os.path.exists(excel_path):
                os.remove(excel_path)
                
            # Retirer le dossier exports fictif s'il est vide
            exports_dir = os.path.dirname(excel_path)
            if os.path.exists(exports_dir) and not os.listdir(exports_dir):
                os.rmdir(exports_dir)

if __name__ == "__main__":
    unittest.main()
