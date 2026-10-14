"""
Firestore rules against the local emulator (dev/docker-compose.yml, which mounts
firestore.rules): every client is denied, whatever its role (plan phase 3). The pages
use Firebase only to sign in; the API reaches Firestore through IAM.
Skipped when the emulator is not running (CI).
"""

import json
import unittest
import urllib.error
import urllib.request

AUTH = "http://localhost:9099/identitytoolkit.googleapis.com/v1"
FIRESTORE = "http://localhost:8081/v1/projects/demo-alj/databases/(default)/documents"

COLLECTIONS = ("competitions", "coaches", "adherents", "planning", "helloasso_items",
               "email_templates", "app_settings", "crm_users", "crm_purchases")


def _emulator_running() -> bool:
    try:
        urllib.request.urlopen("http://localhost:8081/", timeout=1)
        urllib.request.urlopen("http://localhost:9099/", timeout=1)
        return True
    except Exception:
        return False


def _post(url: str, body: dict, headers: dict = None) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", **(headers or {})})
    return json.load(urllib.request.urlopen(req, timeout=10))


def _status(path: str, id_token: str, method: str = "GET", body: dict = None) -> int:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{FIRESTORE}/{path}", data, method=method,
                                 headers={"Authorization": "Bearer " + id_token,
                                          "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return 200
    except urllib.error.HTTPError as e:
        return e.code


@unittest.skipUnless(_emulator_running(), "Firebase emulator not running (dev/docker-compose.yml)")
class TestRulesDenyEveryClient(unittest.TestCase):

    def _google_sign_in(self, email: str, **claims) -> str:
        """A verified Google account; custom claims set through the emulator's admin API."""
        id_token = json.dumps({"sub": "test-" + email, "email": email, "email_verified": True})
        account = _post(f"{AUTH}/accounts:signInWithIdp?key=demo",
                        {"postBody": f"id_token={id_token}&providerId=google.com",
                         "requestUri": "http://localhost", "returnSecureToken": True})
        self.addCleanup(_post, f"{AUTH}/projects/demo-alj/accounts:delete",
                        {"localId": account["localId"]}, {"Authorization": "Bearer owner"})
        if not claims:
            return account["idToken"]
        _post(f"{AUTH}/projects/demo-alj/accounts:update",
              {"localId": account["localId"], "customAttributes": json.dumps(claims)},
              {"Authorization": "Bearer owner"})
        return _post(f"{AUTH}/accounts:signInWithIdp?key=demo",
                     {"postBody": f"id_token={id_token}&providerId=google.com",
                      "requestUri": "http://localhost", "returnSecureToken": True})["idToken"]

    def test_every_role_is_denied(self):
        accounts = {
            "admin (club domain)": self._google_sign_in("test.admin@alj-escalade.fr"),
            "admin (claim)": self._google_sign_in("claim.admin@example.com", admin=True),
            "coach (claim)": self._google_sign_in("claim.coach@example.com", coach=True),
            "readonly (claim)": self._google_sign_in("claim.readonly@example.com", readonly=True),
        }
        for who, token in accounts.items():
            for collection in COLLECTIONS:
                with self.subTest(who=who, collection=collection):
                    self.assertEqual(_status(f"{collection}?pageSize=1", token), 403)
                    self.assertEqual(_status(f"{collection}/rules-probe", token, "PATCH",
                                             {"fields": {"x": {"stringValue": "y"}}}), 403)

    def test_server_access_is_not_affected(self):
        """The emulator's admin token stands for IAM access (server, desktop app)."""
        self.assertEqual(_status("competitions?pageSize=1", "owner"), 200)


if __name__ == "__main__":
    unittest.main()
