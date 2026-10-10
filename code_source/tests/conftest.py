"""Configuration pytest commune : sortie console en UTF-8 (émojis des modules applicatifs)."""
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

import pytest

# Variables du mode dev (dev/dev.env) : retirées pour que les tests restent en mode
# production même si le développeur les a chargées dans son shell.
_DEV_ENV_KEYS = ("ALJ_ENV", "FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST",
                 "MEMBER_BACKEND", "ALJ_DATA_DIR",
                 "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM_EMAIL",
                 "GMAIL_USER_EMAIL", "GMAIL_CLIENT_ID", "GMAIL_REFRESH_TOKEN")


@pytest.fixture(autouse=True)
def _production_environment(monkeypatch):
    for key in _DEV_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
