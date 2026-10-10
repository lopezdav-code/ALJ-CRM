"""
Environnement d'exécution : production (défaut) ou développement local sur l'émulateur Firebase.

Source unique de vérité pour tout ce qui diffère entre les deux modes côté Firestore
(URL, jeton, projet) et configuration transmise au navigateur. Les e-mails ne sont pas
concernés : en dev, le SMTP de l'application pointe vers Mailpit (dev/dev.env).

- ``ALJ_ENV`` absent ou ``prod`` : comportement de production inchangé (Cloud Run,
  client lourd, serveur local sans émulateur).
- ``ALJ_ENV=dev`` : tout passe par l'émulateur Firebase (Auth + Firestore) du projet
  ``demo-alj``. Un projet ``demo-*`` n'existe pas en production : même mal configuré,
  aucun appel ne peut atteindre les vraies données. Voir ``code_source/dev/``.

Les variables d'environnement sont relues à chaque appel (tests, rechargement).
"""
import os
from typing import Any, Dict, Optional

PROD_FIRESTORE_BASE_URL = "https://firestore.googleapis.com/v1"
DEV_PROJECT_ID = "demo-alj"
EMULATOR_ADMIN_TOKEN = "owner"  # jeton admin de l'émulateur : ignore les règles de sécurité

DEFAULT_PUBLIC_FIRESTORE_EMULATOR = "localhost:8081"
DEFAULT_PUBLIC_AUTH_EMULATOR = "http://localhost:9099"


def env() -> str:
    return "dev" if (os.environ.get("ALJ_ENV") or "").strip().lower() == "dev" else "prod"


def is_dev() -> bool:
    return env() == "dev"


def firestore_emulator_host() -> Optional[str]:
    """Hôte de l'émulateur Firestore (variable standard Firebase), uniquement en mode dev."""
    if not is_dev():
        return None
    return (os.environ.get("FIRESTORE_EMULATOR_HOST") or "").strip() or None


def validate() -> None:
    """Refuse un mode dev incohérent (fail-closed). Appelé au démarrage du serveur."""
    if not is_dev():
        return
    if os.environ.get("K_SERVICE"):
        raise RuntimeError("ALJ_ENV=dev est interdit sur Cloud Run (K_SERVICE présent).")
    missing = [k for k in ("FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST")
               if not (os.environ.get(k) or "").strip()]
    if missing:
        raise RuntimeError(f"ALJ_ENV=dev exige l'émulateur Firebase : {', '.join(missing)} manquant(s).")


def firestore_base_url() -> str:
    host = firestore_emulator_host()
    return f"http://{host}/v1" if host else PROD_FIRESTORE_BASE_URL


def emulator_token() -> Optional[str]:
    return EMULATOR_ADMIN_TOKEN if firestore_emulator_host() else None


def project_id_override() -> Optional[str]:
    return DEV_PROJECT_ID if is_dev() else None


def client_config() -> Dict[str, Any]:
    """Configuration exposée au navigateur (/runtime-config.js) : rien en production."""
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
