"""Tests du rendu HTML des corps d'e-mail (balises simples + liens externes)."""
import os
import sys
import unittest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from email_html import text_to_html


class TestTextToHtml(unittest.TestCase):
    def test_bold_italic_underline_preserved(self):
        out = text_to_html("Texte <b>gras</b>, <i>italique</i> et <u>souligné</u>.")
        self.assertIn("<b>gras</b>", out)
        self.assertIn("<i>italique</i>", out)
        self.assertIn("<u>soulignés</u>" if False else "<u>souligné</u>", out)

    def test_link_restored_with_href(self):
        out = text_to_html('Visitez <a href="https://www.exemple.fr">notre site</a> !')
        self.assertIn('<a href="https://www.exemple.fr" target="_blank" style="color:#2563EB;">notre site</a>', out)

    def test_mailto_link(self):
        out = text_to_html('<a href="mailto:contact@alj.fr">Écrivez-nous</a>')
        self.assertIn('<a href="mailto:contact@alj.fr"', out)

    def test_dangerous_scheme_neutralized(self):
        out = text_to_html('<a href="javascript:alert(1)">Cliquez</a>')
        self.assertNotIn("<a ", out)
        self.assertIn("Cliquez", out)

    def test_text_escaped_and_newlines(self):
        out = text_to_html("Ligne 1\n<b>Ligne 2</b>")
        self.assertIn("Ligne 1<br><b>Ligne 2</b>", out)

    def test_variable_braces_not_swallowed(self):
        # Les variables {first_name}… ne contiennent pas de balise : elles restent telles quelles
        out = text_to_html("Bonjour {first_name}, épreuve {no_competition}.")
        self.assertIn("Bonjour {first_name}", out)
        self.assertIn("{no_competition}", out)


if __name__ == "__main__":
    unittest.main()
