"""Tests du moteur de variables des e-mails (aperçu + envoi, Communications)."""
import os
import sys
import unittest
from types import SimpleNamespace

_test_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from domain.utils import format_montant
from presentation.workers import apply_template_variables


def _member(**overrides):
    base = {"user_first_name": "Jean", "user_last_name": "DUPONT", "licence_ffme": "123456"}
    base.update(overrides)
    return SimpleNamespace(**base)


class TestFormatMontant(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(format_montant(15), "15")
        self.assertEqual(format_montant(15.0), "15")
        self.assertEqual(format_montant(15.5), "15,50")
        self.assertEqual(format_montant("15.5"), "15,50")
        self.assertEqual(format_montant(0), "0")
        self.assertEqual(format_montant(None), "")
        self.assertEqual(format_montant("abc"), "")


class TestApplyTemplateVariables(unittest.TestCase):
    BODY = ("Bonjour {first_name} {last_name}, licence {num_licence}, "
            "compétition n° {no_competition} : {name_competition}, "
            "montant {montant_competition} €.")

    def test_all_variables_replaced(self):
        ctx = {"no_competition": "18846", "name_competition": "Coupe du Rhône 2027",
               "montant_competition": "15"}
        out = apply_template_variables(self.BODY, _member(), ctx)
        self.assertNotIn("{", out)
        self.assertIn("Bonjour Jean DUPONT", out)
        self.assertIn("licence 123456", out)
        self.assertIn("compétition n° 18846 : Coupe du Rhône 2027", out)
        self.assertIn("montant 15 €.", out)

    def test_subject_replaced(self):
        ctx = {"no_competition": "18846", "name_competition": "Coupe du Rhône 2027"}
        self.assertEqual(
            apply_template_variables("Compétition {name_competition} (n° {no_competition})", _member(), ctx),
            "Compétition Coupe du Rhône 2027 (n° 18846)"
        )

    def test_without_context_variables_kept_as_is(self):
        out = apply_template_variables(self.BODY, _member(), None)
        self.assertIn("Bonjour Jean DUPONT", out)
        self.assertIn("licence 123456", out)
        self.assertIn("{no_competition}", out)
        self.assertIn("{name_competition}", out)
        self.assertIn("{montant_competition}", out)

    def test_accents_and_legacy_syntax(self):
        ctx = {"no_competition": "18846"}
        out = apply_template_variables("Bonjour {Prénom} {Nom}, épreuve {no_competition}", _member(), ctx)
        self.assertEqual(out, "Bonjour Jean DUPONT, épreuve 18846")

    def test_none_and_empty(self):
        self.assertEqual(apply_template_variables(None, _member(), {}), "")
        self.assertEqual(apply_template_variables("", _member(), None), "")

    def test_date_competition_replaced(self):
        ctx = {
            "no_competition": "18846",
            "name_competition": "Coupe du Rhône 2027",
            "date_competition": "15/10/2026"
        }
        out = apply_template_variables("Date : {date_competition}", _member(), ctx)
        self.assertEqual(out, "Date : 15/10/2026")

    def test_whatsapp_link_replaced_with_whatapp_id_token(self):
        ctx = {
            "no_competition": "18846",
            "name_competition": "Coupe du Rhône 2027",
            "whatapp_Id": "https://chat.whatsapp.com/invite123"
        }
        out = apply_template_variables("Lien du groupe : {whatapp_Id}", _member(), ctx)
        self.assertEqual(out, "Lien du groupe : https://chat.whatsapp.com/invite123")

    def test_whatsapp_link_fallback_keys(self):
        ctx = {
            "whatsapp_link": "https://chat.whatsapp.com/invite456"
        }
        out1 = apply_template_variables("Groupe : {whatapp_Id}", _member(), ctx)
        self.assertEqual(out1, "Groupe : https://chat.whatsapp.com/invite456")

        out2 = apply_template_variables("Groupe : {whatsapp_link} et {whatsapp_id}", _member(), ctx)
        self.assertEqual(out2, "Groupe : https://chat.whatsapp.com/invite456 et https://chat.whatsapp.com/invite456")

    def test_whatsapp_token_kept_if_no_context(self):
        out = apply_template_variables("Rejoins {whatapp_Id}", _member(), None)
        self.assertEqual(out, "Rejoins {whatapp_Id}")


if __name__ == "__main__":
    unittest.main()
