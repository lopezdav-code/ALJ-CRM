"""
Runtime environment: production (default) or local development on the Firebase emulator.

Single source of truth for everything that differs between the two modes on the Firestore
side (URL, token, project) and for the configuration sent to the browser. E-mails are not
involved: in dev, the application's SMTP settings point to Mailpit (dev/dev.env).

- ``ALJ_ENV`` unset or ``prod``: unchanged production behaviour (Cloud Run, desktop
  client, local server without emulator).
- ``ALJ_ENV=dev``: everything goes through the Firebase emulator (Auth + Firestore) of the
  ``demo-alj`` project. A ``demo-*`` project does not exist in production: even when
  misconfigured, no call can reach the real data. See ``code_source/dev/``.

Environment variables are read again on every call (tests, reload).
"""
import os
from typing import Any, Dict, Optional

PROD_FIRESTORE_BASE_URL = "https://firestore.googleapis.com/v1"
DEV_PROJECT_ID = "demo-alj"
EMULATOR_ADMIN_TOKEN = "owner"  # emulator admin token: bypasses the security rules

DEFAULT_PUBLIC_FIRESTORE_EMULATOR = "localhost:8081"
DEFAULT_PUBLIC_AUTH_EMULATOR = "http://localhost:9099"


def env() -> str:
    return "dev" if (os.environ.get("ALJ_ENV") or "").strip().lower() == "dev" else "prod"


def is_dev() -> bool:
    return env() == "dev"


def firestore_emulator_host() -> Optional[str]:
    """Firestore emulator host (standard Firebase variable), in dev mode only."""
    if not is_dev():
        return None
    return (os.environ.get("FIRESTORE_EMULATOR_HOST") or "").strip() or None


def validate() -> None:
    """Reject an inconsistent dev mode (fail-closed). Called at server startup."""
    if not is_dev():
        return
    if os.environ.get("K_SERVICE"):
        raise RuntimeError("ALJ_ENV=dev is forbidden on Cloud Run (K_SERVICE is set).")
    missing = [k for k in ("FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST")
               if not (os.environ.get(k) or "").strip()]
    if missing:
        raise RuntimeError(f"ALJ_ENV=dev requires the Firebase emulator: missing {', '.join(missing)}.")


def firestore_base_url() -> str:
    host = firestore_emulator_host()
    return f"http://{host}/v1" if host else PROD_FIRESTORE_BASE_URL


def emulator_token() -> Optional[str]:
    return EMULATOR_ADMIN_TOKEN if firestore_emulator_host() else None


def project_id_override() -> Optional[str]:
    return DEV_PROJECT_ID if is_dev() else None


def client_config() -> Dict[str, Any]:
    """Configuration exposed to the browser (/runtime-config.js): nothing in production."""
    if not is_dev():
        return {"env": "prod"}
    return {
        "env": "dev",
        "projectId": DEV_PROJECT_ID,
        "firestoreEmulator": (os.environ.get("ALJ_PUBLIC_FIRESTORE_EMULATOR")
                              or DEFAULT_PUBLIC_FIRESTORE_EMULATOR).strip(),
        "authEmulator": (os.environ.get("ALJ_PUBLIC_AUTH_EMULATOR")
                         or DEFAULT_PUBLIC_AUTH_EMULATOR).strip(),
    }
