"""
Tests unitaires pour le Lot 4 : Déploiement Cloud Run, Dockerfile, et routes de production.
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_code_root = os.path.dirname(_tests_dir)
_src_dir = os.path.join(_code_root, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from domain.constants import APP_VERSION, get_active_season
from server import health_check, webhook_helloasso_ping, root_route


class TestCloudRunLot4(unittest.TestCase):
    """Vérifie la conformité des artefacts conteneurisés et des routes de production."""

    def test_version_consistency(self):
        """Vérifie que la constante APP_VERSION correspond au fichier VERSION."""
        version_file = os.path.join(_code_root, "VERSION")
        self.assertTrue(os.path.isfile(version_file), "Le fichier VERSION doit exister.")
        with open(version_file, "r", encoding="utf-8") as f:
            v_content = f.read().strip()
        self.assertEqual(APP_VERSION, v_content, "La version dans constants.py et VERSION doivent correspondre.")
        self.assertEqual(APP_VERSION, "2.5.9")

    def test_requirements_docker(self):
        """Vérifie que requirements-docker.txt exclut les paquets Windows lourds."""
        req_docker_path = os.path.join(_code_root, "requirements-docker.txt")
        self.assertTrue(os.path.isfile(req_docker_path), "requirements-docker.txt doit exister.")
        with open(req_docker_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Vérifier uniquement les lignes actives (hors commentaires)
        active_lines = [
            line.strip().lower()
            for line in content.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        package_names = [
            line.split("==")[0].split(">=")[0].split("<=")[0].strip()
            for line in active_lines
        ]

        # Doit contenir les briques backend
        self.assertIn("fastapi", package_names)
        self.assertIn("uvicorn", package_names)
        self.assertIn("requests", package_names)
        self.assertIn("python-dotenv", package_names)

        # Ne doit JAMAIS contenir les dépendances client lourd desktop Windows
        self.assertNotIn("pywin32", package_names)
        self.assertNotIn("pyside6", package_names)
        self.assertNotIn("python-docx", package_names)

    def test_dockerfile_configuration(self):
        """Vérifie la structure du Dockerfile pour Cloud Run."""
        dockerfile_path = os.path.join(_code_root, "Dockerfile")
        self.assertTrue(os.path.isfile(dockerfile_path), "Dockerfile doit exister.")
        with open(dockerfile_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("FROM python:", content)
        self.assertIn("EXPOSE 8080", content)
        self.assertIn("HEALTHCHECK", content)
        self.assertIn("PORT", content)
        self.assertIn("uvicorn server:app", content)
        self.assertIn("requirements-docker.txt", content)

    def test_dockerignore_security(self):
        """Vérifie que les secrets et fichiers de données sont rigoureusement exclus."""
        ignore_path = os.path.join(_code_root, ".dockerignore")
        self.assertTrue(os.path.isfile(ignore_path), ".dockerignore doit exister.")
        with open(ignore_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(".env", content)
        self.assertIn("*.db", content)
        self.assertIn("venv/", content)

    def test_deploy_scripts_exist(self):
        """Vérifie la présence des scripts de déploiement Cloud Run."""
        bat_path = os.path.join(_code_root, "deploy_cloud_run.bat")
        sh_path = os.path.join(_code_root, "deploy_cloud_run.sh")
        root_bat_path = os.path.join(os.path.dirname(_code_root), "deploy_cloud_run.bat")

        self.assertTrue(os.path.isfile(bat_path), "deploy_cloud_run.bat doit exister dans code_source.")
        self.assertTrue(os.path.isfile(sh_path), "deploy_cloud_run.sh doit exister dans code_source.")
        self.assertTrue(os.path.isfile(root_bat_path), "deploy_cloud_run.bat doit exister à la racine.")

        with open(bat_path, "r", encoding="utf-8") as f:
            bat_content = f.read()
        self.assertIn("gcloud run deploy", bat_content)
        self.assertIn("--min-instances 0", bat_content)

    def test_health_check_endpoint(self):
        """Vérifie le retour JSON de l'endpoint /health."""
        data = health_check()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "alj-escalade-api")
        self.assertEqual(data["version"], APP_VERSION)
        self.assertEqual(data["season"], get_active_season())
        self.assertIn("timestamp", data)

    def test_webhook_helloasso_ping_endpoint(self):
        """Vérifie le retour HTTP 200 de l'endpoint probe GET /webhooks/helloasso."""
        data = webhook_helloasso_ping()
        self.assertEqual(data["status"], "active")
        self.assertEqual(data["endpoint"], "helloasso-webhook-receiver")
        self.assertIn("Payment", data["supported_events"])
        self.assertIn("Order", data["supported_events"])

    def test_root_route_redirect(self):
        """Vérifie que la route racine redirige vers /competitions ou renvoie les liens API."""
        resp = root_route()
        if hasattr(resp, "status_code"):
            self.assertEqual(resp.status_code, 302)
            self.assertIn("/competitions", resp.headers.get("location", ""))
        else:
            self.assertIn("service", resp)
            self.assertIn("version", resp)


if __name__ == "__main__":
    unittest.main()
