"""
Firestore rules against the local emulator (dev/docker-compose.yml, which mounts
firestore.rules): an unverified account named like a club address must not get a
role. Skipped when the emulator is not running (CI).
"""

import json
import unittest
import urllib.error
import urllib.request

AUTH = "http://localhost:9099/identitytoolkit.googleapis.com/v1"
FIRESTORE = "http://localhost:8081/v1/projects/demo-alj/databases/(default)/documents"


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


def _read_status(path: str, id_token: str) -> int:
    req = urllib.request.Request(f"{FIRESTORE}/{path}", headers={"Authorization": "Bearer " + id_token})
    try:
        urllib.request.urlopen(req, timeout=10)
        return 200
    except urllib.error.HTTPError as e:
        return e.code


@unittest.skipUnless(_emulator_running(), "Firebase emulator not running (dev/docker-compose.yml)")
class TestRulesRequireVerifiedEmail(unittest.TestCase):

    def _sign_up(self, email: str) -> str:
        account = _post(f"{AUTH}/accounts:signUp?key=demo",
                        {"email": email, "password": "not-a-real-password", "returnSecureToken": True})
        self.addCleanup(_post, f"{AUTH}/projects/demo-alj/accounts:delete",
                        {"localId": account["localId"]}, {"Authorization": "Bearer owner"})
        return account["idToken"]

    def test_unverified_club_address_has_no_role(self):
        for email in ("intruder@alj-escalade.fr", "lopez.dav@gmail.com", "stephane.loridant@orange.fr"):
            with self.subTest(email=email):
                token = self._sign_up(email)
                self.assertEqual(_read_status("crm_users?pageSize=1", token), 403)
                self.assertEqual(_read_status("adherents?pageSize=1", token), 403)

    def test_verified_google_admin_keeps_access(self):
        id_token = json.dumps({"sub": "test-admin", "email": "test.admin@alj-escalade.fr", "email_verified": True})
        account = _post(f"{AUTH}/accounts:signInWithIdp?key=demo",
                        {"postBody": f"id_token={id_token}&providerId=google.com",
                         "requestUri": "http://localhost", "returnSecureToken": True})
        self.addCleanup(_post, f"{AUTH}/projects/demo-alj/accounts:delete",
                        {"localId": account["localId"]}, {"Authorization": "Bearer owner"})
        self.assertEqual(_read_status("crm_users?pageSize=1", account["idToken"]), 200)


if __name__ == "__main__":
    unittest.main()
