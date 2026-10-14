"""
Tests unitaires pour CompetitionResultsBatchService.
Vérifie la détection des compétitions passées sans résultats, la configuration de l'e-mail,
le scraping mocké, la génération de l'e-mail HTML et l'envoi de notification.
"""

import os
import sys
import unittest
import datetime
from unittest.mock import patch, MagicMock

# Injection du chemin src
_tests_dir = os.path.dirname(os.path.abspath(__file__))
_code_root = os.path.dirname(os.path.dirname(_tests_dir))
_src_dir = os.path.join(_code_root, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from infrastructure.competition_results_batch_service import (
    CompetitionResultsBatchService,
    DEFAULT_NOTIFICATION_EMAIL,
    SETTING_NOTIFICATION_EMAIL
)
from infrastructure.sqlite_repository import SqliteRepository


class TestCompetitionResultsBatchService(unittest.TestCase):

    def setUp(self):
        SqliteRepository.setup_database()

    def test_default_notification_email(self):
        """L'adresse de notification par défaut est david.lopez@alj-jonage.fr."""
        email = CompetitionResultsBatchService.get_notification_email()
        self.assertIn("@", email)
        self.assertEqual(email, DEFAULT_NOTIFICATION_EMAIL)

    def test_set_and_get_custom_notification_email(self):
        """L'adresse de notification peut être mise à jour et rechargée depuis les réglages."""
        custom_email = "notif.test@alj-jonage.fr"
        ok = CompetitionResultsBatchService.set_notification_email(custom_email)
        self.assertTrue(ok)
        self.assertEqual(CompetitionResultsBatchService.get_notification_email(), custom_email)

        # Nettoyage
        CompetitionResultsBatchService.set_notification_email(DEFAULT_NOTIFICATION_EMAIL)

    def test_set_invalid_email_raises_error(self):
        """Une adresse sans @ ou invalide lève une ValueError."""
        with self.assertRaises(ValueError):
            CompetitionResultsBatchService.set_notification_email("adresse_invalide")

    def test_is_competition_past(self):
        """Vérifie le calcul de date pour déterminer si une épreuve est passée."""
        today = datetime.date(2026, 10, 14)

        # 1. Compétition hier -> passée
        comp_past = {"nom": "Open Passé", "date_competition": "2026-10-10"}
        self.assertTrue(CompetitionResultsBatchService.is_competition_past(comp_past, today=today))

        # 2. Compétition aujourd'hui -> passée / en cours
        comp_today = {"nom": "Open Aujourd'hui", "date_competition": "2026-10-14"}
        self.assertTrue(CompetitionResultsBatchService.is_competition_past(comp_today, today=today))

        # 3. Compétition future -> non passée
        comp_future = {"nom": "Open Futur", "date_competition": "2026-11-20"}
        self.assertFalse(CompetitionResultsBatchService.is_competition_past(comp_future, today=today))

        # 4. Compétition multi-jours avec date_fin dans le futur -> non passée
        comp_multi = {"nom": "Championnat", "date_competition": "2026-10-10", "date_fin": "2026-10-18"}
        self.assertFalse(CompetitionResultsBatchService.is_competition_past(comp_multi, today=today))

    def test_has_results(self):
        """Vérifie la détection de présence ou d'absence de résultats."""
        # 1. Aucun classement et pas de synchro -> pas de résultat
        comp_no_res = {
            "nom": "Open 1",
            "participants": [{"nom": "DUPONT", "prenom": "Jean", "classement": ""}],
            "resultats_synced_at": ""
        }
        self.assertFalse(CompetitionResultsBatchService.has_results(comp_no_res))

        # 2. Classement et synchro présents -> a des résultats
        comp_with_res = {
            "nom": "Open 2",
            "participants": [{"nom": "DUPONT", "prenom": "Jean", "classement": "2"}],
            "resultats_synced_at": "2026-10-11T18:00:00"
        }
        self.assertTrue(CompetitionResultsBatchService.has_results(comp_with_res))

    def test_build_results_email_html_structure(self):
        """Le générateur d'e-mail HTML produit un tableau structuré avec médailles et liens."""
        comp_data = [{
            "id": "comp_10",
            "nom": "Open Régional Bloc Jonage",
            "date": "2026-10-10",
            "lieu": "Jonage",
            "url": "https://mycompet.ffme.fr/resultat/resultat_13660",
            "athletes": [
                {
                    "nom": "BULAND",
                    "prenom": "Julia",
                    "num_licence": "930654",
                    "categorie": "U15 Femme",
                    "classement": "1",
                    "total_categorie": 28,
                    "resultat_ffme": "1er / 28",
                    "performance": "Finale (Top)"
                },
                {
                    "nom": "DUPONT",
                    "prenom": "Jean",
                    "num_licence": "123456",
                    "categorie": "U17 Homme",
                    "classement": "2",
                    "total_categorie": 34,
                    "resultat_ffme": "2e / 34",
                    "performance": "Finale 4t 4z"
                }
            ]
        }]

        html = CompetitionResultsBatchService.build_results_email_html(comp_data)
        self.assertIn("Open Régional Bloc Jonage", html)
        self.assertIn("BULAND", html)
        self.assertIn("DUPONT", html)
        self.assertIn("🥇", html)  # Médaille d'or 1er
        self.assertIn("🥈", html)  # Médaille d'argent 2e
        self.assertIn("https://mycompet.ffme.fr/resultat/resultat_13660", html)
        self.assertTrue("batch quotidien ALJ Escalade" in html)

    @patch("infrastructure.competition_results_batch_service.EmailRepository.send_email")
    def test_run_daily_batch_sends_email_when_results_found(self, mock_send_email):
        """Le batch quotidien envoie un e-mail dès que des résultats sont découverts."""
        mock_send_email.return_value = True

        test_comp = {
            "id": 999,
            "nom": "Test Batch Comp",
            "date_competition": "2026-10-10",
            "lieu": "Jonage",
            "participants": [
                {"adherent_id": 1, "nom": "MARTIN", "prenom": "Alice", "num_licence": "654321"}
            ],
            "resultats_synced_at": ""
        }

        # Mock list_pending_competitions et sync_results_for_competition
        with patch.object(CompetitionResultsBatchService, "list_pending_competitions", return_value=[test_comp]):
            with patch.object(
                CompetitionResultsBatchService,
                "sync_results_for_competition",
                return_value=(1, [{"nom": "MARTIN", "prenom": "Alice", "classement": "1", "resultat_ffme": "1er / 20"}], "https://mycompet.test")
            ):
                res = CompetitionResultsBatchService.run_daily_batch(force=True)

                self.assertEqual(res["status"], "success")
                self.assertEqual(res["competitions_checked"], 1)
                self.assertEqual(res["competitions_updated"], 1)
                self.assertTrue(res["email_sent"])
                mock_send_email.assert_called_once()


if __name__ == "__main__":
    unittest.main()
