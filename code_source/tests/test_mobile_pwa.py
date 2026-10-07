"""
Tests unitaires pour l'application Web Mobile PWA (competitions.html, manifest, service worker).
"""

import os
import sys
import unittest
import json

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_tests_dir), "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from server import get_manifest, get_sw, get_competitions_page


class TestMobilePWA(unittest.TestCase):
    """Vérifie la conformité PWA et les fonctionnalités de l'interface mobile."""

    def test_manifest_endpoint(self):
        resp = get_manifest()
        self.assertEqual(resp.media_type, "application/manifest+json")
        self.assertTrue(os.path.exists(resp.path))
        with open(resp.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["name"], "ALJ Escalade — Compétitions")
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["theme_color"], "#1E293B")

    def test_service_worker_endpoint(self):
        resp = get_sw()
        self.assertEqual(resp.media_type, "application/javascript")
        self.assertTrue(os.path.exists(resp.path))
        with open(resp.path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("alj-escalade-v4", content)
        self.assertIn("addEventListener(\"fetch\"", content)

    def test_competitions_html_pwa_and_email_features(self):
        resp = get_competitions_page()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(os.path.exists(resp.path))
        with open(resp.path, "r", encoding="utf-8") as f:
            html = f.read()

        # Vérifications PWA
        self.assertIn('<link rel="manifest" href="/manifest.webmanifest">', html)
        self.assertIn('<meta name="theme-color" content="#1E293B">', html)
        self.assertIn("serviceWorker.register('/sw.js')", html)

        # Vérifications Envoi d'E-mails
        self.assertIn('id="p-email-btn"', html)
        self.assertIn('id="email-modal"', html)
        self.assertIn('id="em-template-select"', html)
        self.assertIn('id="em-preview-box"', html)
        self.assertIn('sendCampaignEmails()', html)

        # Vérifications Appel 1-clic téléphone
        self.assertIn('href="tel:', html)

        # Vérifications Chargement Groupe Compétition (non sélectionné + non invité)
        self.assertIn('parts.push(newParticipant(a.id, false, "non_invite"))', html)
        self.assertIn('statut || (isSelected ? "en_attente" : "non_invite")', html)

        # Vérifications Édition Compétition (navigation showPage, réinitialisation et retour)
        self.assertIn('showPage("comps");', html)
        self.assertIn('editSourcePage', html)
        self.assertIn('openParticipants(savedCompId)', html)

        # Vérifications Écran HelloAsso & Rattachement des paiements
        self.assertIn('data-page="helloasso"', html)
        self.assertIn('id="page-helloasso"', html)
        self.assertIn('id="ha-attach-modal"', html)
        self.assertIn('openAttachModal', html)
        self.assertIn('saveAttachment', html)
        self.assertIn('renderHelloAssoPage', html)
        self.assertIn('id="ha-items-list"', html)

        # Vérifications Mode Consultation (Lecture Seule) selon l'utilisateur
        self.assertIn('function isCoachUser()', html)
        self.assertIn('function isReadOnlyUser()', html)
        self.assertIn('function isAuthorizedUser()', html)
        self.assertIn('function applyRolePermissions()', html)
        self.assertIn('id="setup-role-badge"', html)
        self.assertIn('id="setup-unauthorized"', html)
        self.assertIn('id="comp-form-card"', html)


if __name__ == "__main__":
    unittest.main()
