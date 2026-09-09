"""Tests de l'auto-réparation du refresh token Google (keyring périmé vs .env frais)."""
import os
import sys
import unittest
from unittest import mock

# Ajustement du chemin d'import
_test_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(os.path.dirname(_test_dir), "src") if os.path.basename(_test_dir) == "tests" else _test_dir
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from infrastructure.google_drive_client import GoogleDriveClient
from infrastructure.secret_store import SecretStore

OLD_CREDS = ("old-client-id", "old-secret", "OLD_REVOKED_TOKEN")
NEW_CREDS = ("new-client-id", "new-secret", "NEW_VALID_TOKEN")


def _write_env(path, creds):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Commentaire à ignorer\n")
        f.write(f"GMAIL_CLIENT_ID={creds[0]}\n")
        f.write(f"GMAIL_CLIENT_SECRET={creds[1]}\n")
        f.write(f"GMAIL_REFRESH_TOKEN={creds[2]}\n")
        f.write(f"GMAIL_USER_EMAIL=test@alj-escalade.fr\n")
        f.write(f"AUTRE_CLE=valeur\n")


def _fake_response(status_code, payload):
    resp = mock.Mock()
    resp.status_code = status_code
    resp.text = str(payload) if status_code != 200 else ""
    resp.json.return_value = payload
    return resp


class TestDriveTokenRepair(unittest.TestCase):

    def setUp(self):
        import tempfile
        self.temp_dir = tempfile.mkdtemp()
        self.env_path = os.path.join(self.temp_dir, ".env")
        _write_env(self.env_path, NEW_CREDS)

    def test_parse_env_credentials(self):
        creds = GoogleDriveClient._parse_env_credentials(self.env_path)
        self.assertEqual(
            creds,
            {"client_id": NEW_CREDS[0], "client_secret": NEW_CREDS[1], "refresh_token": NEW_CREDS[2]},
        )
        self.assertIsNone(GoogleDriveClient._parse_env_credentials(os.path.join(self.temp_dir, "inexistant.env")))

    def test_candidates_store_first_then_env(self):
        with mock.patch.object(SecretStore, "get_secret", side_effect=lambda k: dict(
                zip(("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"), OLD_CREDS)).get(k, "")):
            candidates = GoogleDriveClient._iter_credential_candidates(env_paths=[self.env_path])
        self.assertEqual(candidates[0], OLD_CREDS)
        self.assertIn(NEW_CREDS, candidates)
        self.assertEqual(len(candidates), 2)

    def test_valid_stored_token_no_repair(self):
        """Le token du SecretStore fonctionne : aucun appel de réparation, un seul appel HTTP."""
        with mock.patch.object(SecretStore, "get_secret", side_effect=lambda k: dict(
                zip(("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"), NEW_CREDS)).get(k, "")), \
             mock.patch.object(SecretStore, "set_secret") as mock_set, \
             mock.patch("infrastructure.google_drive_client.requests.post",
                        return_value=_fake_response(200, {"access_token": "TOKEN_OK"})) as mock_post:
            token = GoogleDriveClient.get_access_token(env_paths=[self.env_path])
        self.assertEqual(token, "TOKEN_OK")
        self.assertEqual(mock_post.call_count, 1)
        mock_set.assert_not_called()

    def test_revoked_stored_token_self_heals_from_env(self):
        """Régression du bug 'invalid_grant' : le keyring contient l'ancien token révoqué,
        le .env contient le nouveau token (assistant OAuth2). Le client doit retenter
        avec le .env puis réparer le SecretStore."""
        responses = [
            _fake_response(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}),
            _fake_response(200, {"access_token": "TOKEN_NEW"}),
        ]
        with mock.patch.object(SecretStore, "get_secret", side_effect=lambda k: dict(
                zip(("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"), OLD_CREDS)).get(k, "")), \
             mock.patch.object(SecretStore, "set_secret") as mock_set, \
             mock.patch("infrastructure.google_drive_client.requests.post", side_effect=responses) as mock_post:
            token = GoogleDriveClient.get_access_token(env_paths=[self.env_path])
        self.assertEqual(token, "TOKEN_NEW")
        self.assertEqual(mock_post.call_count, 2)
        # Le trousseau doit être réparé avec les identifiants valides du .env
        repaired = {call.args[0]: call.args[1] for call in mock_set.call_args_list}
        self.assertEqual(repaired["GMAIL_REFRESH_TOKEN"], NEW_CREDS[2])
        self.assertEqual(repaired["GMAIL_CLIENT_ID"], NEW_CREDS[0])

    def test_all_candidates_rejected_raises(self):
        responses = [
            _fake_response(400, {"error": "invalid_grant"}),
            _fake_response(400, {"error": "invalid_grant"}),
        ]
        with mock.patch.object(SecretStore, "get_secret", side_effect=lambda k: dict(
                zip(("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"), OLD_CREDS)).get(k, "")), \
             mock.patch("infrastructure.google_drive_client.requests.post", side_effect=responses):
            with self.assertRaises(Exception) as ctx:
                GoogleDriveClient.get_access_token(env_paths=[self.env_path])
        self.assertIn("Échec de l'obtention du token Google", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
