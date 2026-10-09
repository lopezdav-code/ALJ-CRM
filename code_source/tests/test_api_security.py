"""
Tests de sécurité de l'API Cloud Run :
- authentification par jeton d'identité Firebase + rôles (miroir de firestore.rules) ;
- vérification des notifications webhook HelloAsso (jeton secret, relecture API).
"""

import datetime
import os
import re
import sys
import time
import unittest
from unittest.mock import patch

_tests_dir = os.path.dirname(os.path.abspath(__file__))
_code_root = os.path.dirname(_tests_dir)
_src_dir = os.path.join(_code_root, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

import helloasso_api
from infrastructure import api_auth
from infrastructure.helloasso_webhook_service import HelloAssoWebhookService, WebhookRejected
from server import app

PROJECT = api_auth.DEFAULT_PROJECT_ID
KID = "test-kid"


def _make_key_and_cert():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "securetoken.test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=1))
            .sign(key, hashes.SHA256()))
    return key, cert.public_bytes(serialization.Encoding.PEM).decode()


KEY, CERT_PEM = _make_key_and_cert()
OTHER_KEY, _ = _make_key_and_cert()


def make_token(email="coach@alj-escalade.fr", key=KEY, kid=KID, aud=PROJECT,
               iss=None, exp_delta=3600, verified=True, **claims):
    now = int(time.time())
    payload = {
        "iss": iss or f"https://securetoken.google.com/{PROJECT}",
        "aud": aud, "sub": "uid-123", "iat": now - 10, "auth_time": now - 10,
        "exp": now + exp_delta, "email": email, "email_verified": verified,
    }
    payload.update(claims)
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})


class _CertsMixin:
    def setUp(self):
        self._saved = dict(api_auth._certs_cache)
        api_auth._certs_cache["keys"] = {KID: CERT_PEM}
        api_auth._certs_cache["expires"] = time.time() + 3600

    def tearDown(self):
        api_auth._certs_cache.update(self._saved)


class TestRoles(unittest.TestCase):

    def test_required_role(self):
        r = api_auth.required_role
        for path in ("/", "/health", "/competitions", "/index", "/sw.js", "/manifest.webmanifest",
                     "/api/web-version", "/webhooks/helloasso", "/annuaire/", "/annuaire/index.html",
                     "/bureau", "/bureau/", "/bureau/adherents", "/static-web/alj-core.js"):
            self.assertIsNone(r("GET", path), path)
        self.assertIsNone(r("POST", "/webhooks/helloasso"))
        self.assertIsNone(r("OPTIONS", "/api/send-email"))
        for path in ("/api/send-email", "/api/helloasso/sync", "/api/email-status", "/api/dashboard",
                     "/map", "/pivot", "/docs", "/openapi.json", "/api/une-route-future"):
            self.assertEqual(r("GET", path), "coach", path)
        self.assertEqual(r("POST", "/api/planning"), "admin")
        self.assertEqual(r("GET", "/api/planning"), "coach")
        self.assertEqual(r("GET", "/annuaire-pirate"), "coach")

    def test_roles_for_claims(self):
        f = api_auth.roles_for_claims
        self.assertEqual(f({"email": "Bureau@ALJ-Escalade.fr", "email_verified": True}),
                         {"admin", "coach"})
        self.assertEqual(f({"email": "lopez.dav@gmail.com", "email_verified": True}), {"admin", "coach"})
        self.assertEqual(f({"email": "stephane.loridant@orange.fr", "email_verified": True}), {"coach"})
        self.assertEqual(f({"email": "muah.did@gmail.com", "email_verified": True}), {"readonly"})
        self.assertEqual(f({"email": "inconnu@gmail.com", "email_verified": True}), set())
        # Adresse non vérifiée : aucun rôle par e-mail
        self.assertEqual(f({"email": "x@alj-escalade.fr", "email_verified": False}), set())
        # Custom claims
        self.assertEqual(f({"email": "a@b.c", "coach": True}), {"coach"})
        self.assertEqual(f({"admin": True}), {"admin", "coach"})
        self.assertTrue(api_auth.has_role({"admin": True}, "coach"))
        self.assertFalse(api_auth.has_role({"readonly": True}, "coach"))

    def test_lists_match_firestore_rules_and_pwa(self):
        """Les listes Python doivent rester identiques à firestore.rules et à la PWA."""
        with open(os.path.join(_code_root, "firestore.rules"), encoding="utf-8") as f:
            rules = f.read()

        def rule_emails(func):
            body = re.search(r"function %s\(\)\s*\{(.*?)\n    \}" % func, rules, re.S).group(1)
            return {e for e in re.findall(r"'([^'@\s]+@[^'\s]+)'", body) if "*" not in e}

        self.assertEqual(rule_emails("isAdmin"), set(api_auth.ADMIN_EMAILS))
        self.assertEqual(rule_emails("isCoach"), set(api_auth.COACH_EMAILS))
        self.assertEqual(rule_emails("isReadOnly"), set(api_auth.READONLY_EMAILS))
        for d in api_auth.ADMIN_EMAIL_DOMAINS:
            self.assertIn(d.replace(".", "\\\\."), rules)

        for page in ("competitions.html", "index.html", os.path.join("shared", "alj-core.js")):
            with open(os.path.join(_code_root, "web", page), encoding="utf-8") as f:
                html = f.read()

            def js_list(name):
                body = re.search(r"const %s = \[(.*?)\];" % name, html, re.S).group(1)
                return set(re.findall(r'"([^"]+)"', body))

            self.assertEqual(js_list("COACH_EMAILS"), set(api_auth.ADMIN_EMAILS) | set(api_auth.COACH_EMAILS), page)
            self.assertEqual(js_list("READONLY_EMAILS"), set(api_auth.READONLY_EMAILS), page)


class TestTokenVerification(_CertsMixin, unittest.TestCase):

    def test_valid_token(self):
        claims = api_auth.verify_firebase_token(make_token())
        self.assertEqual(claims["email"], "coach@alj-escalade.fr")

    def assertRejected(self, token, status=401):
        with self.assertRaises(api_auth.AuthError) as ctx:
            api_auth.verify_firebase_token(token)
        self.assertEqual(ctx.exception.status_code, status)

    def test_invalid_tokens(self):
        self.assertRejected("pas-un-jwt")
        self.assertRejected(make_token(exp_delta=-3600))                       # expiré
        self.assertRejected(make_token(aud="autre-projet"))                    # mauvaise audience
        self.assertRejected(make_token(iss="https://accounts.google.com"))     # mauvais émetteur
        self.assertRejected(make_token(key=OTHER_KEY))                         # signature falsifiée
        self.assertRejected(make_token(sub=""))                                # sujet vide
        self.assertRejected(make_token(auth_time=int(time.time()) + 3600))     # auth_time futur
        hs = jwt.encode({"aud": PROJECT, "sub": "x"}, "secret-de-test-suffisamment-long-32o", algorithm="HS256", headers={"kid": KID})
        self.assertRejected(hs)                                                # algorithme HS256

    def test_unknown_kid_refetches(self):
        with patch.object(api_auth, "_fetch_certs", return_value={KID: CERT_PEM}) as fetch:
            self.assertRejected(make_token(kid="inconnu"))
            fetch.assert_called_once()


class TestAuthMiddleware(_CertsMixin, unittest.TestCase):

    def setUp(self):
        super().setUp()
        self.client = TestClient(app)
        self.env = patch.dict(os.environ, {"ALJ_API_AUTH": "required"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        super().tearDown()

    def get(self, path, token=None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return self.client.get(path, headers=headers)

    def test_public_routes(self):
        for path in ("/health", "/api/web-version", "/webhooks/helloasso",
                     "/bureau/", "/bureau/adherents", "/static-web/alj-core.js"):
            self.assertEqual(self.get(path).status_code, 200, path)

    def test_protected_routes(self):
        r = self.get("/api/email-status")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.headers.get("www-authenticate"), "Bearer")
        self.assertEqual(self.get("/api/email-status", "abc").status_code, 401)
        self.assertEqual(self.get("/api/email-status", make_token(email="muah.did@gmail.com")).status_code, 403)
        self.assertEqual(self.get("/api/email-status", make_token(email="pirate@gmail.com")).status_code, 403)
        self.assertEqual(self.get("/api/email-status", make_token()).status_code, 200)
        self.assertEqual(self.get("/docs").status_code, 401)
        self.assertEqual(self.client.post("/api/send-email", json={}).status_code, 401)
        self.assertEqual(self.client.post("/api/helloasso/sync").status_code, 401)

    def test_planning_write_requires_admin(self):
        coach = make_token(email="stephane.loridant@orange.fr")
        r = self.client.post("/api/planning", json=[], headers={"Authorization": f"Bearer {coach}"})
        self.assertEqual(r.status_code, 403)
        with patch("server.SqliteRepository.save_planning_data") as save:
            r = self.client.post("/api/planning", json=[], headers={"Authorization": f"Bearer {make_token()}"})
            self.assertEqual(r.status_code, 200)
            save.assert_called_once()

    def test_cors_preflight_not_blocked(self):
        r = self.client.options("/api/send-email", headers={
            "Origin": "https://exemple.fr", "Access-Control-Request-Method": "POST"})
        self.assertEqual(r.status_code, 200)

    def test_auth_disabled_locally(self):
        with patch.dict(os.environ, {"ALJ_API_AUTH": "off"}):
            self.assertEqual(self.get("/api/email-status").status_code, 200)
        with patch.dict(os.environ, {"ALJ_API_AUTH": "", "K_SERVICE": "alj-escalade-api"}):
            self.assertTrue(api_auth.auth_enforced())
        with patch.dict(os.environ, {"ALJ_API_AUTH": ""}):
            os.environ.pop("K_SERVICE", None)
            self.assertFalse(api_auth.auth_enforced())


VERIFIED_ITEM = {
    "id": 501, "amount": 1500, "state": "Processed",
    "order": {"id": 9001, "formSlug": "competitions"},
    "user": {"firstName": "Lucas", "lastName": "MARTIN"},
    "customFields": [{"name": "Numéro de licence FFME", "answer": "654321"}],
}


class TestWebhookVerification(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    def secrets(self, token=""):
        real = api_auth.SecretStore.get_secret
        return patch("infrastructure.helloasso_webhook_service.SecretStore.get_secret",
                     side_effect=lambda k: token if k == "HELLOASSO_WEBHOOK_TOKEN" else real(k))

    def test_token_required_when_configured(self):
        with self.secrets("s3cret"), patch.object(helloasso_api, "credentials_configured", return_value=False), \
             patch.object(HelloAssoWebhookService, "process_webhook", return_value={"status": "success"}) as proc:
            r = self.client.post("/webhooks/helloasso", json={"eventType": "Order", "data": {}})
            self.assertEqual(r.status_code, 401)
            r = self.client.post("/webhooks/helloasso?token=faux", json={"eventType": "Order", "data": {}})
            self.assertEqual(r.status_code, 401)
            proc.assert_not_called()
            r = self.client.post("/webhooks/helloasso?token=s3cret", json={"eventType": "Order", "data": {}})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["verified"], "token")
            proc.assert_called_once()

    def test_production_refuses_unverifiable_notifications(self):
        with self.secrets(""), patch.dict(os.environ, {"ALJ_API_AUTH": "required"}), \
             patch.object(helloasso_api, "credentials_configured", return_value=False), \
             patch.object(HelloAssoWebhookService, "process_webhook") as proc:
            r = self.client.post("/webhooks/helloasso", json={"eventType": "Order", "data": {}})
            self.assertEqual(r.status_code, 503)
            proc.assert_not_called()

    def test_forged_payload_is_replaced_by_api_data(self):
        """Montant/état/licence forgés dans le payload : seules les données API comptent."""
        forged = {"eventType": "Order", "data": {"id": 9001, "items": [
            {"id": 501, "amount": 999999, "state": "Processed",
             "customFields": [{"name": "Licence", "answer": "000000"}]},
            {"id": 777, "amount": 1500, "state": "Processed"},  # inexistant chez HelloAsso
        ]}}
        with self.secrets(""), patch.object(helloasso_api, "credentials_configured", return_value=True), \
             patch.object(helloasso_api, "get_item", side_effect=lambda i: VERIFIED_ITEM if i == 501 else None) as gi, \
             patch.object(HelloAssoWebhookService, "process_webhook",
                          side_effect=lambda p, items=None: {"status": "success", "items": items}) as proc:
            r = self.client.post("/webhooks/helloasso", json=forged)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["verified"], "api")
            self.assertEqual([c.args[0] for c in gi.call_args_list], [501, 777])
            self.assertEqual(proc.call_args.kwargs["items"], [VERIFIED_ITEM])

    def test_payment_event_resolves_items_through_api(self):
        payload = {"eventType": "Payment", "data": {"id": 42, "amount": 1500, "state": "Authorized"}}
        with patch.object(helloasso_api, "get_payment", return_value={"id": 42, "order": {"id": 9001}, "items": []}), \
             patch.object(helloasso_api, "get_order", return_value={"id": 9001, "items": [{"id": 501}]}), \
             patch.object(helloasso_api, "get_item", return_value=VERIFIED_ITEM):
            self.assertEqual(HelloAssoWebhookService.fetch_verified_items(payload), [VERIFIED_ITEM])

    def test_api_failure_returns_503(self):
        with self.secrets(""), patch.object(helloasso_api, "credentials_configured", return_value=True), \
             patch.object(helloasso_api, "get_item", side_effect=helloasso_api.HelloAssoApiError("timeout")):
            r = self.client.post("/webhooks/helloasso", json={"eventType": "Order", "data": {"items": [{"id": 1}]}})
            self.assertEqual(r.status_code, 503)

    def test_process_webhook_uses_verified_items(self):
        """Avec des articles vérifiés, le contenu du payload n'est pas utilisé."""
        with patch.object(HelloAssoWebhookService, "extract_items_from_payload") as extract, \
             patch("infrastructure.helloasso_webhook_service.CompetitionRepository") as repo:
            repo.list_competitions.return_value = []
            repo.list_adherents.return_value = []
            repo.list_helloasso_links.return_value = {}
            report = HelloAssoWebhookService.process_webhook({"eventType": "Order"}, items=[VERIFIED_ITEM])
            extract.assert_not_called()
            self.assertEqual(report["processed_count"], 1)
            self.assertEqual(report["matched_count"], 0)

    def test_check_token_constant_time(self):
        with self.secrets("abc"):
            self.assertTrue(HelloAssoWebhookService.check_token("abc"))
            self.assertFalse(HelloAssoWebhookService.check_token("abd"))
            self.assertFalse(HelloAssoWebhookService.check_token(None))
        with self.secrets(""):
            self.assertIsNone(HelloAssoWebhookService.check_token("abc"))


if __name__ == "__main__":
    unittest.main()
