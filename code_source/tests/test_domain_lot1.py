import os
import sys
import unittest

# Ajustement du chemin pour importer les modules depuis 'src'
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from domain.models import Member, InsuranceOptions
from domain.validators import validate_amount, validate_email
from domain.constants import get_active_season, get_drive_temp_filename
from attestation_generator import get_safe_filename

class TestDomainLot1(unittest.TestCase):

    def test_member_from_and_to_dict(self):
        """Vérifie que l'instanciation, from_dict et to_dict du modèle Member fonctionnent parfaitement."""
        data = {
            "order_ref": "ORDER-12345",
            "order_date": "2026-08-08",
            "status": "Validated",
            "tarif_name": "Adulte Autonome",
            "amount": 246.50,
            "user_lastName": "Dupont",
            "user_firstName": "Jean",
            "payer_firstName": "Jean",
            "payer_lastName": "Dupont",
            "payer_email": "jean.dupont@test.com",
            "champ_Date de naissance de l'adhérent": "15/07/1990",
            "champ_Sexe": "M",
            "champ_Nationalité": "Française",
            "opt_Assurance Base": "Oui",
            "opt_Montant Assurance Base": "5.50"
        }

        member = Member.from_dict(data)
        self.assertEqual(member.order_ref, "ORDER-12345")
        self.assertEqual(member.user_last_name, "Dupont")
        self.assertEqual(member.amount, 246.50)
        self.assertEqual(member.birth_date, "15/07/1990")
        self.assertTrue(member.insurance.has_base)
        self.assertEqual(member.insurance.amount_base, 5.50)

        # Export dictionnaire
        exported = member.to_dict()
        self.assertEqual(exported["order_ref"], "ORDER-12345")
        self.assertEqual(exported["user_lastName"], "Dupont")
        self.assertEqual(exported["opt_Assurance Base"], "Oui")
        self.assertEqual(exported["opt_Montant Assurance Base"], 5.50)

    def test_validate_amount(self):
        """Vérifie la robustesse du validateur de montant financier."""
        self.assertEqual(validate_amount(246.50), 246.50)
        self.assertEqual(validate_amount("246,50"), 246.50)
        self.assertEqual(validate_amount(" 246.50 € "), 246.50)
        self.assertEqual(validate_amount("246 500,50 EUR"), 246500.50)
        self.assertEqual(validate_amount(""), 0.0)
        self.assertEqual(validate_amount(None), 0.0)

        with self.assertRaises(ValueError):
            validate_amount("invalide-123")

    def test_validate_email(self):
        """Vérifie la robustesse du validateur d'e-mail."""
        self.assertEqual(validate_email("test@domain.com"), "test@domain.com")
        self.assertEqual(validate_email("  TEST@DOMAIN.COM  "), "test@domain.com")
        self.assertEqual(validate_email(""), "")
        self.assertEqual(validate_email(None), "")

        with self.assertRaises(ValueError):
            validate_email("invalide_email_sans_at")

    def test_get_active_season(self):
        """Vérifie la configuration dynamique des saisons."""
        season = get_active_season()
        self.assertIsInstance(season, str)
        self.assertGreater(len(season), 0)
        
        # Test du helper de fichier temporaire
        temp_fn = get_drive_temp_filename()
        self.assertIn(season, temp_fn)
        self.assertTrue(temp_fn.endswith(".xlsx"))

    def test_get_safe_filename_unique(self):
        """Vérifie que la génération de nom d'attestation prend en compte la référence unique de commande."""
        fn_simple = get_safe_filename("Dupont", "Jean")
        self.assertEqual(fn_simple, "Attestation_DUPONT_Jean.docx")

        fn_unique = get_safe_filename("Dupont", "Jean", "ORDER-12345")
        self.assertEqual(fn_unique, "Attestation_DUPONT_Jean_ORDER-12345.docx")

if __name__ == "__main__":
    unittest.main()
