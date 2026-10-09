"""
Tests unitaires pour le service et l'endpoint Webhook HelloAsso.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_tests_dir), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from infrastructure.helloasso_webhook_service import HelloAssoWebhookService
import asyncio
from server import webhook_helloasso


class TestHelloAssoWebhookService(unittest.TestCase):
    """Vérifie le parsing et le traitement des webhooks HelloAsso."""

    def test_extract_items_from_order_payload(self):
        payload = {
            "eventType": "Order",
            "data": {
                "id": 1001,
                "items": [
                    {
                        "id": 501,
                        "amount": 1500,
                        "name": "Inscription épreuve",
                        "customFields": [{"name": "Numéro de licence FFME", "answer": "710083"}]
                    }
                ]
            }
        }
        event_type, items = HelloAssoWebhookService.extract_items_from_payload(payload)
        self.assertEqual(event_type, "Order")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], 501)

    def test_extract_items_from_payment_payload(self):
        payload = {
            "eventType": "Payment",
            "data": {
                "id": 9001,
                "amount": 1800,
                "state": "Authorized",
                "paymentMeans": "Card",
                "payer": {"firstName": "Michel", "lastName": "DUPONT"},
                "order": {"id": 8001, "formSlug": "campagne-test"},
                "customFields": [{"name": "Licence", "answer": "123456"}]
            }
        }
        event_type, items = HelloAssoWebhookService.extract_items_from_payload(payload)
        self.assertEqual(event_type, "Payment")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], 9001)
        self.assertEqual(items[0]["amount"], 1800)

    @patch("infrastructure.competition_firestore_repository.CompetitionFirestoreRepository.get_app_setting", return_value="")
    @patch("infrastructure.competition_firestore_repository.CompetitionFirestoreRepository.apply_helloasso_payment")
    @patch("infrastructure.competition_firestore_repository.CompetitionFirestoreRepository.set_item_link")
    @patch("infrastructure.competition_firestore_repository.CompetitionFirestoreRepository.sync_helloasso_mirror")
    @patch("infrastructure.competition_firestore_repository.CompetitionFirestoreRepository.list_helloasso_links", return_value={})
    @patch("infrastructure.competition_firestore_repository.CompetitionFirestoreRepository.list_adherents")
    @patch("infrastructure.competition_firestore_repository.CompetitionFirestoreRepository.list_competitions")
    def test_process_webhook_match_successful(
        self,
        mock_list_comps,
        mock_list_adhs,
        mock_list_links,
        mock_sync_mirror,
        mock_set_link,
        mock_apply_payment,
        mock_get_setting
    ):
        """Vérifie le rapprochement complet d'un item avec mise à jour du paiement."""
        mock_comp = MagicMock()
        mock_comp.to_dict.return_value = {"id": 10, "id_ffme": "18846", "nom": "Coupe Rhône"}
        mock_list_comps.return_value = [mock_comp]

        mock_list_adhs.return_value = [
            {"id": 101, "num_licence": "654321", "nom": "MARTIN", "prenom": "Lucas"}
        ]
        mock_apply_payment.return_value = True

        payload = {
            "eventType": "Payment",
            "data": {
                "id": 7777,
                "amount": 1500,
                "state": "Processed",
                "order": {"id": 9999, "formSlug": "regularisation"},
                "user": {"firstName": "Lucas", "lastName": "MARTIN"},
                "customFields": [
                    {"name": "Numéro de licence FFME", "answer": "654321"},
                    {"name": "Numéro de la compétition", "answer": "18846"}
                ]
            }
        }

        report = HelloAssoWebhookService.process_webhook(payload)
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["matched_count"], 1)
        self.assertEqual(len(report["anomalies"]), 0)

        match = report["matches"][0]
        self.assertEqual(match["competition_id"], 10)
        self.assertEqual(match["adherent_id"], 101)
        self.assertEqual(match["montant"], 15.0)

        mock_apply_payment.assert_called_once()
        mock_set_link.assert_called_once()

    def test_items_of_other_forms_are_ignored(self):
        """Un achat boutique (autre formulaire) n'entre pas dans le miroir des compétitions."""
        tshirt = {"id": 210752710, "amount": 1700, "state": "Processed", "name": "T shirt technique Enfant",
                  "order": {"id": 1, "formSlug": "vetements-club-al-jonage-2026-2027", "formType": "Shop"}}
        compet = {"id": 42, "amount": 1500, "state": "Processed",
                  "order": {"id": 2, "formSlug": "regularisation-inscription-competiteurs-2026-2027"}}
        url = ("https://www.helloasso.com/associations/amicale-laique-de-jonage/evenements/"
               "regularisation-inscription-competiteurs-2026-2027")
        Repo = "infrastructure.competition_firestore_repository.CompetitionFirestoreRepository"
        with patch(f"{Repo}.get_app_setting", return_value=url), \
             patch(f"{Repo}.setup_database"), \
             patch(f"{Repo}.sync_helloasso_mirror") as mirror, \
             patch(f"{Repo}.list_competitions", return_value=[]), \
             patch(f"{Repo}.list_adherents", return_value=[]), \
             patch(f"{Repo}.list_helloasso_links", return_value={}):
            report = HelloAssoWebhookService.process_webhook({"eventType": "Order"}, items=[tshirt])
            self.assertEqual(report["status"], "ignored")
            self.assertEqual(report["other_forms"], ["vetements-club-al-jonage-2026-2027"])
            mirror.assert_not_called()

            report = HelloAssoWebhookService.process_webhook({"eventType": "Order"}, items=[tshirt, compet])
            self.assertEqual(report["processed_count"], 1)
            mirror.assert_called_once()
            self.assertEqual(mirror.call_args.kwargs["raw_items"][0]["id"], 42)

    def test_summarize_items_uses_order_date(self):
        from domain.competition_matching import summarize_items
        rows = summarize_items([{"id": 1, "amount": 100, "order": {"id": 9, "date": "2026-10-07T15:45:10+02:00"}}])
        self.assertEqual(rows[0]["date_item"], "2026-10-07T15:45:10+02:00")

    def test_fastapi_webhook_endpoint(self):
        """Teste l'appel sur le route handler FastAPI /webhooks/helloasso."""
        payload = {
            "eventType": "Ping",
            "data": {}
        }
        with patch("helloasso_api.credentials_configured", return_value=False), \
             patch.dict(os.environ, {"ALJ_API_AUTH": "off"}):
            resp = asyncio.run(webhook_helloasso(payload))
        self.assertEqual(resp["status"], "ignored")


if __name__ == "__main__":
    unittest.main()
