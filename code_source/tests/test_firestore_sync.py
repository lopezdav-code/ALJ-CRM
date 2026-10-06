"""
Tests unitaires pour le module de synchronisation Google Cloud Firestore (firestore_sync.py).
"""

import os
import sys
import unittest
import datetime
from unittest.mock import patch, MagicMock

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_tests_dir), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from infrastructure.firestore_sync import (
    python_to_firestore_value,
    firestore_to_python_value,
    dict_to_firestore_fields,
    firestore_fields_to_dict,
    prepare_firestore_data,
    FirestoreSyncService
)


class TestFirestoreSync(unittest.TestCase):
    """Vérifie la sérialisation, la projection et les échanges REST avec Firestore."""

    def test_types_roundtrip_conversion(self):
        """Vérifie que la conversion Python -> Firestore -> Python préserve l'intégrité des types."""
        sample_data = {
            "nom": "DUPONT",
            "age": 28,
            "prix": 18.5,
            "est_actif": True,
            "est_nul": None,
            "date": "2026-10-05T14:30:00Z",
            "tags": ["bloc", "difficile"],
            "meta": {
                "coach": "Adrien",
                "nb": 3
            }
        }

        # Python -> Firestore fields
        fields = dict_to_firestore_fields(sample_data)
        self.assertEqual(fields["nom"], {"stringValue": "DUPONT"})
        self.assertEqual(fields["age"], {"integerValue": "28"})
        self.assertEqual(fields["prix"], {"doubleValue": 18.5})
        self.assertEqual(fields["est_actif"], {"booleanValue": True})
        self.assertEqual(fields["est_nul"], {"nullValue": None})
        self.assertIn("arrayValue", fields["tags"])
        self.assertIn("mapValue", fields["meta"])

        # Firestore fields -> Python
        restored = firestore_fields_to_dict(fields)
        self.assertEqual(restored["nom"], "DUPONT")
        self.assertEqual(restored["age"], 28)
        self.assertEqual(restored["prix"], 18.5)
        self.assertEqual(restored["est_actif"], True)
        self.assertIsNone(restored["est_nul"])
        self.assertEqual(restored["tags"], ["bloc", "difficile"])
        self.assertEqual(restored["meta"], {"coach": "Adrien", "nb": 3})

    def test_prepare_firestore_data_collections(self):
        """Vérifie l'extraction des données SQLite vers la structure NoSQL."""
        data = prepare_firestore_data()
        self.assertIn("competitions", data)
        self.assertIn("adherents", data)
        self.assertIn("planning", data)
        self.assertIn("email_templates", data)

        # Vérifier structure d'une compétition si existante
        if data["competitions"]:
            first_comp = next(iter(data["competitions"].values()))
            self.assertIn("nom", first_comp)
            self.assertIn("prix", first_comp)
            self.assertIn("participants", first_comp)
            self.assertIsInstance(first_comp["participants"], list)

        # Vérifier structure d'un adhérent
        if data["adherents"]:
            first_adh = next(iter(data["adherents"].values()))
            self.assertIn("nom", first_adh)
            self.assertIn("prenom", first_adh)
            self.assertIn("licence_ffme", first_adh)

    @patch("requests.patch")
    def test_push_collection_rest(self, mock_patch):
        """Vérifie l'envoi d'une collection via l'API REST v1."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_patch.return_value = mock_resp

        sample_docs = {
            "comp_1": {"nom": "Coupe Rhône", "prix": 15.0}
        }

        report = FirestoreSyncService.push_collection(
            collection_name="competitions",
            documents=sample_docs,
            project_id="test-alj",
            access_token="fake_token"
        )

        self.assertEqual(report["total"], 1)
        self.assertEqual(report["synced"], 1)
        self.assertEqual(report["errors_count"], 0)
        mock_patch.assert_called_once()
        args, kwargs = mock_patch.call_args
        self.assertIn("projects/test-alj/databases/(default)/documents/competitions/comp_1", args[0])
        self.assertIn("fields", kwargs["json"])

    @patch("infrastructure.competition_repository.CompetitionRepository.apply_helloasso_payment")
    @patch("infrastructure.competition_repository.CompetitionRepository.set_selection")
    @patch("requests.get")
    def test_pull_competition_updates(self, mock_get, mock_set_sel, mock_apply_pay):
        """Vérifie la réconciliation des modifications mobiles depuis Firestore."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "fields": {
                "participants": {
                    "arrayValue": {
                        "values": [
                            {
                                "mapValue": {
                                    "fields": {
                                        "adherent_id": {"integerValue": "105"},
                                        "selectionne": {"booleanValue": True},
                                        "statut_paiement": {"stringValue": "paye"},
                                        "montant_paye": {"doubleValue": 18.0},
                                        "commande_helloasso": {"stringValue": "CMD-999"}
                                    }
                                }
                            }
                        ]
                    }
                }
            }
        }
        mock_get.return_value = mock_resp

        report = FirestoreSyncService.pull_competition_updates(
            competition_id=3,
            project_id="test-alj",
            access_token="fake_token"
        )

        self.assertEqual(report["status"], "success")
        self.assertEqual(report["participants_reconciled"], 1)
        mock_set_sel.assert_called_once_with(3, 105, True)
        mock_apply_pay.assert_called_once_with(
            competition_id=3,
            adherent_id=105,
            montant_paye=18.0,
            order_ref="CMD-999"
        )

    def test_firestore_rules_file(self):
        """Vérifie la présence et la cohérence syntaxique du fichier firestore.rules."""
        rules_path = os.path.join(os.path.dirname(_tests_dir), "firestore.rules")
        self.assertTrue(os.path.exists(rules_path))
        with open(rules_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("rules_version = '2';", content)
        self.assertIn("match /competitions/{competitionId}", content)
        self.assertIn("match /participants/{participantId}", content)
        self.assertIn("match /adherents/{adherentId}", content)
        self.assertIn("match /planning/{creneauId}", content)


if __name__ == "__main__":
    unittest.main()
