"""
Tests du mode d'exécution (production par défaut / dev sur l'émulateur Firebase) :
- production inchangée sans variable, rien d'exposé au navigateur ;
- mode dev refusé sur Cloud Run ou sans émulateur (fail-closed) ;
- URL, jeton et projet Firestore redirigés vers l'émulateur en dev uniquement ;
- route /runtime-config.js ;
- garde du script de données fictives.
"""

import os
import sys
import unittest
from unittest.mock import patch

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_code_root = os.path.dirname(_tests_dir)
_src_dir = os.path.join(_code_root, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from fastapi.testclient import TestClient

from infrastructure import runtime_env
from infrastructure.cloud_database import RestStore
from infrastructure.firestore_client import FirestoreClient

DEV_ENV = {
    "ALJ_ENV": "dev",
    "FIRESTORE_EMULATOR_HOST": "localhost:8081",
    "FIREBASE_AUTH_EMULATOR_HOST": "localhost:9099",
}
DEV_KEYS = list(DEV_ENV) + ["K_SERVICE", "ALJ_PUBLIC_FIRESTORE_EMULATOR", "ALJ_PUBLIC_AUTH_EMULATOR"]


def _env(**values):
    """Environnement propre : variables du mode dev retirées puis `values` appliquées."""
    base = {k: v for k, v in os.environ.items() if k not in DEV_KEYS}
    base.update(values)
    return patch.dict(os.environ, base, clear=True)


class TestProductionParDefaut(unittest.TestCase):

    def test_prod_sans_variable(self):
        with _env():
            self.assertEqual(runtime_env.env(), "prod")
            self.assertFalse(runtime_env.is_dev())
            runtime_env.validate()  # ne lève rien
            self.assertEqual(runtime_env.firestore_base_url(), "https://firestore.googleapis.com/v1")
            self.assertIsNone(runtime_env.emulator_token())
            self.assertIsNone(runtime_env.project_id_override())
            self.assertEqual(runtime_env.client_config(), {"env": "prod"})

    def test_emulateur_ignore_hors_mode_dev(self):
        """Une variable d'émulateur oubliée dans le shell ne détourne pas la production."""
        with _env(FIRESTORE_EMULATOR_HOST="localhost:8081"):
            self.assertIsNone(runtime_env.firestore_emulator_host())
            self.assertEqual(runtime_env.firestore_base_url(), "https://firestore.googleapis.com/v1")

    def test_valeur_inconnue_vaut_prod(self):
        with _env(ALJ_ENV="staging"):
            self.assertEqual(runtime_env.env(), "prod")


class TestModeDev(unittest.TestCase):

    def test_redirection_vers_emulateur(self):
        with _env(**DEV_ENV):
            runtime_env.validate()
            self.assertEqual(runtime_env.firestore_base_url(), "http://localhost:8081/v1")
            self.assertEqual(runtime_env.emulator_token(), "owner")
            self.assertEqual(runtime_env.project_id_override(), "demo-alj")
            self.assertEqual(runtime_env.client_config(), {
                "env": "dev", "projectId": "demo-alj",
                "firestoreEmulator": "localhost:8081", "authEmulator": "http://localhost:9099",
            })

    def test_refuse_sur_cloud_run(self):
        with _env(K_SERVICE="alj-escalade-api", **DEV_ENV):
            with self.assertRaises(RuntimeError):
                runtime_env.validate()

    def test_refuse_sans_emulateur(self):
        for missing in ("FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST"):
            values = {k: v for k, v in DEV_ENV.items() if k != missing}
            with self.subTest(missing=missing), _env(**values):
                with self.assertRaises(RuntimeError):
                    runtime_env.validate()

    def test_clients_firestore_branches_sur_emulateur(self):
        with _env(**DEV_ENV):
            store = RestStore()
            self.assertEqual(store.project_id, "demo-alj")
            self.assertEqual(store._token(), "owner")
            self.assertTrue(store._base.startswith("http://localhost:8081/v1/projects/demo-alj/"))
            self.assertEqual(FirestoreClient.get_project_id(), "demo-alj")
            self.assertEqual(FirestoreClient.get_access_token(), "owner")
            self.assertTrue(FirestoreClient.database_url().startswith("http://localhost:8081/v1/projects/demo-alj/"))


class TestRouteRuntimeConfig(unittest.TestCase):

    def setUp(self):
        from server import app
        self.client = TestClient(app)

    def test_production_publique_sans_detail(self):
        with _env(ALJ_API_AUTH="required"):
            resp = self.client.get("/runtime-config.js")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["cache-control"], "no-store")
        self.assertIn("javascript", resp.headers["content-type"])
        self.assertEqual(resp.text.strip(), 'window.ALJ_RUNTIME = Object.freeze({"env": "prod"});')

    def test_dev_expose_l_emulateur(self):
        with _env(**DEV_ENV):
            resp = self.client.get("/runtime-config.js")
        self.assertIn('"env": "dev"', resp.text)
        self.assertIn('"projectId": "demo-alj"', resp.text)


class TestGardeSeed(unittest.TestCase):

    def test_refuse_hors_emulateur(self):
        sys.path.insert(0, os.path.join(_code_root, "dev", "seed"))
        try:
            import seed_emulator
        finally:
            sys.path.pop(0)
        with _env():
            with self.assertRaises(SystemExit):
                seed_emulator.ensure_emulator()
        with _env(**DEV_ENV):
            self.assertEqual(seed_emulator.ensure_emulator(), "localhost:8081")


if __name__ == "__main__":
    unittest.main()
