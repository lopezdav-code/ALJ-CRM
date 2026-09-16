"""Tests du moteur de variables des e-mails (aperçu + envoi, Communications)."""
import os
import sys
import unittest
from types import SimpleNamespace

_test_dir = os.path.dirname(os.path.abspath(__file__))
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


if __name__ == "__main__":
    unittest.main()
