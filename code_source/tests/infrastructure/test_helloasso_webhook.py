"""
Tests unitaires pour le service et l'endpoint Webhook HelloAsso.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_tests_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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

    def test_check_and_notify_all_paid_success(self):
        """Vérifie l'envoi d'e-mail récapitulatif lorsque tous les compétiteurs ont réglé."""
        from domain.competition_models import Competition, Participant
        from infrastructure.helloasso_webhook_service import HelloAssoWebhookService

        comp = Competition(id=10, nom="Open Régional Bloc", date_competition="2026-11-20", prix=15.0)
        p1 = Participant(competition_id=10, adherent_id=1, nom="DUPONT", prenom="Alice",
                         num_licence="123456", selectionne=True, statut_paiement="paye",
                         montant_paye=15.0, commande_helloasso="CMD-1", date_synchro_helloasso="2026-10-14")
        p2 = Participant(competition_id=10, adherent_id=2, nom="MARTIN", prenom="Bob",
                         num_licence="654321", selectionne=True, statut_paiement="paye",
                         montant_paye=15.0, commande_helloasso="CMD-2", date_synchro_helloasso="2026-10-14")
        p3 = Participant(competition_id=10, adherent_id=3, nom="DURAND", prenom="Charlie",
                         num_licence="999999", selectionne=False, statut_paiement="non_invite")

        Repo = "infrastructure.competition_firestore_repository.CompetitionFirestoreRepository"
        settings_store = {}

        def mock_get_setting(key, default=""):
            return settings_store.get(key, default)

        def mock_save_setting(key, value):
            settings_store[key] = value
            return True

        with patch(f"{Repo}.get_competition", return_value=comp), \
             patch(f"{Repo}.list_participants", return_value=[p1, p2, p3]), \
             patch(f"{Repo}.get_app_setting", side_effect=mock_get_setting), \
             patch(f"{Repo}.save_app_setting", side_effect=mock_save_setting), \
             patch("infrastructure.competition_results_batch_service.CompetitionResultsBatchService.get_notification_email", return_value="coach@alj-escalade.fr"), \
             patch("infrastructure.email_repository.EmailRepository.send_email", return_value=True) as mock_send:

            res = HelloAssoWebhookService.check_and_notify_all_paid(10)
            self.assertTrue(res)
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args.kwargs
            self.assertEqual(call_kwargs["to_email"], "coach@alj-escalade.fr")
            self.assertIn("Open Régional Bloc", call_kwargs["subject"])
            self.assertIn("DUPONT", call_kwargs["html_body"])
            self.assertIn("MARTIN", call_kwargs["html_body"])
            self.assertIn("30.00 €", call_kwargs["html_body"])

            # Deuxième appel : déduplication active, pas de réexpédition
            res_again = HelloAssoWebhookService.check_and_notify_all_paid(10)
            self.assertFalse(res_again)
            self.assertEqual(mock_send.call_count, 1)

    def test_check_and_notify_all_paid_incomplete(self):
        """Ne déclenche pas d'e-mail si au moins un compétiteur sélectionné n'a pas encore payé."""
        from domain.competition_models import Competition, Participant
        from infrastructure.helloasso_webhook_service import HelloAssoWebhookService

        comp = Competition(id=11, nom="Coupe de France Difficulté", prix=20.0)
        p1 = Participant(competition_id=11, adherent_id=1, nom="DUPONT", prenom="Alice", selectionne=True, statut_paiement="paye")
        p2 = Participant(competition_id=11, adherent_id=2, nom="MARTIN", prenom="Bob", selectionne=True, statut_paiement="en_attente")

        Repo = "infrastructure.competition_firestore_repository.CompetitionFirestoreRepository"
        with patch(f"{Repo}.get_competition", return_value=comp), \
             patch(f"{Repo}.list_participants", return_value=[p1, p2]), \
             patch(f"{Repo}.get_app_setting", return_value=""), \
             patch(f"{Repo}.save_app_setting"), \
             patch("infrastructure.email_repository.EmailRepository.send_email") as mock_send:

            res = HelloAssoWebhookService.check_and_notify_all_paid(11)
            self.assertFalse(res)
            mock_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
