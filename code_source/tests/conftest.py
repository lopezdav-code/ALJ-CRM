"""Configuration pytest commune : sortie console en UTF-8 (émojis des modules applicatifs)."""
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

import pytest

# Dev mode variables (dev/dev.env): removed so the tests stay in production mode
# even if the developer loaded them into their shell.
_DEV_ENV_KEYS = ("ALJ_ENV", "FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST",
                 "MEMBER_BACKEND", "ALJ_DATA_DIR",
                 "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM_EMAIL",
                 "GMAIL_USER_EMAIL", "GMAIL_CLIENT_ID", "GMAIL_REFRESH_TOKEN")


@pytest.fixture(autouse=True)
def _production_environment(monkeypatch):
    for key in _DEV_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _test_client_host(monkeypatch):
    """Starlette's TestClient sends `Host: testserver`: accepted by the local-server guard in tests only."""
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from infrastructure import api_auth
    monkeypatch.setattr(api_auth, "LOCAL_HOSTS", api_auth.LOCAL_HOSTS | {"testserver"})
