"""
Tests unitaires pour le service d'expédition d'e-mails et les endpoints FastAPI associés.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_tests_dir), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import asyncio
from infrastructure.email_dispatch_service import EmailDispatchService
from server import get_email_templates, preview_email, send_email_api


class TestEmailDispatchService(unittest.TestCase):
    """Vérifie la résolution des variables, l'aperçu et l'envoi d'e-mails."""

    def test_preview_with_variables(self):
        comp_ctx = {
            "name_competition": "Coupe Régionale Bugey",
            "no_competition": "18866",
            "montant_competition": "18,00 €",
            "date_competition": "03/10/2026"
        }
        recipient = {
            "first_name": "Éden",
            "last_name": "COCHE",
            "licence_ffme": "615830",
            "email": "eden.coche@example.com"
        }
        template_subj = "Convocation {name_competition} - {first_name}"
        template_body = "Bonjour {first_name} {last_name},\nTa sélection pour {name_competition} (#{no_competition}) est confirmée.\nMontant : {montant_competition}."

        with patch.object(EmailDispatchService, "get_competition_context", return_value=comp_ctx):
            preview = EmailDispatchService.preview(
                subject=template_subj,
                body=template_body,
                recipient=recipient,
                competition_id=3,
                add_signature=False
            )

            self.assertIn("Convocation Coupe Régionale Bugey - Éden", preview["subject"])
            self.assertIn("Bonjour Éden COCHE", preview["body_plain"])
            self.assertIn("Coupe Régionale Bugey (#18866)", preview["body_plain"])
            self.assertIn("18,00 €", preview["body_plain"])
            self.assertIn("<div", preview["body_html"])

    @patch("infrastructure.email_repository.EmailRepository.send_email")
    def test_dispatch_emails_success(self, mock_send):
        mock_send.return_value = True

        recipients = [
            {"id": 1, "first_name": "Alice", "last_name": "DURAND", "email": "alice@example.com", "licence_ffme": "111111"},
            {"id": 2, "first_name": "Bob", "last_name": "LEFEVRE", "email": "bob@example.com", "licence_ffme": "222222"}
        ]

        res = EmailDispatchService.dispatch_emails(
            subject="Information {first_name}",
            body="Bonjour {first_name}, rappel licence {num_licence}.",
            recipients=recipients,
            add_signature=False
        )

        self.assertEqual(res["status"], "success")
        self.assertEqual(res["sent_count"], 2)
        self.assertEqual(res["errors_count"], 0)
        self.assertEqual(mock_send.call_count, 2)

    def test_fastapi_preview_and_templates_endpoints(self):
        """Teste les route handlers FastAPI /api/email-templates et /api/preview-email."""
        # 1. Templates
        res_t = get_email_templates()
        self.assertEqual(res_t["status"], "success")
        self.assertIsInstance(res_t["templates"], list)
        template_names = [t.get("name") for t in res_t["templates"]]
        self.assertIn("Compétition - 1er Inscription", template_names)
        self.assertIn("Compétition - relance", template_names)

        # 2. Preview
        preview_req = {
            "subject": "Test {first_name}",
            "body": "Bonjour {first_name}",
            "recipient": {"first_name": "Paul", "last_name": "NOEL"}
        }
        res_p = preview_email(preview_req)
        self.assertEqual(res_p["status"], "success")
        self.assertEqual(res_p["preview"]["subject"], "Test Paul")
        self.assertIn("Bonjour Paul", res_p["preview"]["body_plain"])


if __name__ == "__main__":
    unittest.main()
