"""
Authentification de l'API FastAPI (Cloud Run).

Principe
--------
- La PWA (web/competitions.html) est connectée à Firebase Authentication (Google).
  Chaque appel à l'API envoie le jeton d'identité Firebase de l'utilisateur dans
  l'en-tête ``Authorization: Bearer <ID token>``.
- Le serveur vérifie la signature du jeton (clés publiques Google), son audience
  (projet Firebase), son émetteur et sa date d'expiration, puis déduit le rôle de
  l'utilisateur avec EXACTEMENT les mêmes règles que firestore.rules
  (admin / coach / lecture seule).
- Toute route non publique exige au minimum le rôle « coach » ; certaines
  écritures exigent « admin » (fail-closed : une nouvelle route est protégée par
  défaut).

Activation
----------
- ``ALJ_API_AUTH=required`` (positionné dans le Dockerfile) ou exécution sur
  Cloud Run (variable ``K_SERVICE`` injectée par la plateforme) : contrôle actif.
- ``ALJ_API_AUTH=off`` : désactivé (serveur local de l'application de bureau,
  qui n'écoute que sur 127.0.0.1).
"""

from __future__ import annotations

import hmac
import os
import re
import threading
import time
from typing import Any, Dict, Optional

import requests

from infrastructure.secret_store import SecretStore

DEFAULT_PROJECT_ID = "smart-amplifier-510811-n6"
FIREBASE_CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/"
    "securetoken@system.gserviceaccount.com"
)

# ---------------------------------------------------------------------------
# Rôles : miroir de firestore.rules (un test vérifie la cohérence des listes).
# ---------------------------------------------------------------------------
ADMIN_EMAIL_DOMAINS = ("alj-escalade.fr",)
ADMIN_EMAILS = frozenset({
    "lopez.dav@gmail.com",
})
COACH_EMAILS = frozenset({
    "stephane.loridant@orange.fr",
})
READONLY_EMAILS = frozenset({
    "muah.did@gmail.com",
    "clement.dlf78@gmail.com",
    "delphine0910@gmail.com",
})

ROLE_LEVELS = {"readonly": 1, "coach": 2, "admin": 3}

# Routes accessibles sans authentification (pages statiques, santé, version,
# webhook HelloAsso qui dispose de sa propre vérification).
PUBLIC_PATHS = frozenset({
    "/",
    "/health",
    "/competitions",
    "/index",
    "/sw.js",
    "/manifest.webmanifest",
    "/favicon.ico",
    "/api/web-version",
    "/webhooks/helloasso",
})
# Portail bureau et ressources communes : pages et scripts publics, données protégées.
PUBLIC_PREFIXES = ("/annuaire", "/bureau", "/static-web")


class AuthError(Exception):
    """Échec d'authentification (401) ou d'autorisation (403)."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def auth_enforced() -> bool:
    """Le contrôle d'accès est-il actif ? (relu à chaque requête)."""
    mode = (os.environ.get("ALJ_API_AUTH") or "").strip().lower()
    if mode in ("required", "on", "1", "true", "yes"):
        return True
    if mode in ("off", "0", "false", "no", "disabled"):
        return False
    return bool(os.environ.get("K_SERVICE"))


def firebase_project_id() -> str:
    return (
        SecretStore.get_secret("FIREBASE_PROJECT_ID")
        or SecretStore.get_secret("GOOGLE_PROJECT_ID")
        or DEFAULT_PROJECT_ID
    )


def required_role(method: str, path: str) -> Optional[str]:
    """Rôle minimal exigé pour une requête (None = route publique)."""
    method = (method or "GET").upper()
    if method == "OPTIONS":  # pré-vol CORS
        return None
    if len(path) > 1:
        path = path.rstrip("/")
    if path in PUBLIC_PATHS:
        return None
    if any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIXES):
        return None
    if path == "/api/planning" and method not in ("GET", "HEAD"):
        return "admin"  # firestore.rules : planning modifiable par les admins
    return "coach"


# ---------------------------------------------------------------------------
# Rôles
# ---------------------------------------------------------------------------
def roles_for_claims(claims: Dict[str, Any]) -> set:
    """Rôles d'un utilisateur, mêmes règles que firestore.rules."""
    roles = set()
    email = str(claims.get("email") or "").strip().lower()
    # Les règles basées sur l'adresse ne valent que pour une adresse vérifiée
    # (toujours le cas pour une connexion Google).
    email_ok = bool(email) and claims.get("email_verified") is True

    is_admin = claims.get("admin") is True or (
        email_ok and (
            any(email.endswith("@" + d) for d in ADMIN_EMAIL_DOMAINS)
            or email in ADMIN_EMAILS
        )
    )
    is_coach = is_admin or claims.get("coach") is True or (email_ok and email in COACH_EMAILS)
    is_readonly = claims.get("readonly") is True or (email_ok and email in READONLY_EMAILS)

    if is_admin:
        roles.add("admin")
    if is_coach:
        roles.add("coach")
    if is_readonly:
        roles.add("readonly")
    return roles


def has_role(claims: Dict[str, Any], role: str) -> bool:
    needed = ROLE_LEVELS[role]
    return any(ROLE_LEVELS[r] >= needed for r in roles_for_claims(claims))


# ---------------------------------------------------------------------------
# Vérification du jeton d'identité Firebase
# ---------------------------------------------------------------------------
_certs_lock = threading.Lock()
_certs_cache: Dict[str, Any] = {"keys": {}, "expires": 0.0}


def _fetch_certs() -> Dict[str, str]:
    resp = requests.get(FIREBASE_CERTS_URL, timeout=10)
    resp.raise_for_status()
    max_age = 3600
    m = re.search(r"max-age=(\d+)", resp.headers.get("Cache-Control", ""))
    if m:
        max_age = int(m.group(1))
    _certs_cache["keys"] = resp.json()
    _certs_cache["expires"] = time.time() + max_age
    return _certs_cache["keys"]


def _public_key_for(kid: str):
    from cryptography.x509 import load_pem_x509_certificate

    with _certs_lock:
        keys = _certs_cache["keys"]
        if time.time() >= _certs_cache["expires"] or kid not in keys:
            try:
                keys = _fetch_certs()
            except Exception as e:  # réseau indisponible
                if kid not in keys:
                    raise AuthError(503, f"Clés de vérification Google indisponibles : {e}")
    pem = keys.get(kid)
    if not pem:
        raise AuthError(401, "Jeton signé par une clé inconnue")
    return load_pem_x509_certificate(pem.encode()).public_key()


def verify_firebase_token(token: str) -> Dict[str, Any]:
    """Vérifie un jeton d'identité Firebase et renvoie ses claims (AuthError sinon)."""
    try:
        import jwt  # PyJWT
    except ImportError:
        raise AuthError(503, "Vérification des jetons indisponible (PyJWT non installé)")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise AuthError(401, "Jeton d'authentification illisible")
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise AuthError(401, "Jeton d'authentification invalide (algorithme)")

    project = firebase_project_id()
    try:
        claims = jwt.decode(
            token,
            _public_key_for(header["kid"]),
            algorithms=["RS256"],
            audience=project,
            issuer=f"https://securetoken.google.com/{project}",
            leeway=60,
            options={"require": ["exp", "iat", "aud", "iss", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise AuthError(401, "Session expirée : reconnectez-vous")
    except jwt.PyJWTError as e:
        raise AuthError(401, f"Jeton d'authentification invalide ({e.__class__.__name__})")

    if not str(claims.get("sub") or "").strip():
        raise AuthError(401, "Jeton d'authentification invalide (sujet)")
    auth_time = claims.get("auth_time")
    if auth_time is not None and float(auth_time) > time.time() + 60:
        raise AuthError(401, "Jeton d'authentification invalide (auth_time)")
    return claims


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def authorize_request(method: str, path: str, authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    """Contrôle d'accès d'une requête. Renvoie les claims (ou None si public /
    contrôle désactivé) ; lève AuthError en cas de refus."""
    role = required_role(method, path)
    if role is None or not auth_enforced():
        return None
    token = bearer_token(authorization)
    if not token:
        raise AuthError(401, "Authentification requise : connectez-vous avec votre compte Google")
    claims = verify_firebase_token(token)
    if not has_role(claims, role):
        raise AuthError(403, f"Accès refusé : rôle « {role} » requis pour {claims.get('email') or 'ce compte'}")
    return claims


async def auth_middleware(request, call_next):
    """Middleware FastAPI/Starlette appliquant authorize_request à chaque requête."""
    from fastapi.responses import JSONResponse

    try:
        request.state.user = authorize_request(
            request.method, request.url.path, request.headers.get("authorization")
        )
    except AuthError as e:
        headers = {"WWW-Authenticate": "Bearer"} if e.status_code == 401 else None
        return JSONResponse(
            {"status": "error", "message": e.message},
            status_code=e.status_code,
            headers=headers,
        )
    return await call_next(request)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(str(a).encode(), str(b).encode())
