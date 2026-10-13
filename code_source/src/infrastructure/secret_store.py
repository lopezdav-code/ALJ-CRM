import os
import sys
from dotenv import load_dotenv
from paths import CODE_ROOT, ROOT_DIR

# Charger le .env embarqué et surcharger avec le .env local
load_dotenv(os.path.join(CODE_ROOT, ".env"))
load_dotenv(os.path.join(ROOT_DIR, ".env"), override=True)

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

SERVICE_NAME = "ALJ_Escalade_Manager"

_FIRESTORE_SECRETS_CACHE: dict = {}
_FIRESTORE_SECRETS_LOADED: bool = False


class SecretStore:
    """
    Gère le stockage et la récupération sécurisée des secrets d'authentification.
    Tente d'utiliser le trousseau d'accès Windows via 'keyring' et se replie sur le fichier '.env'.
    Sur Cloud Run, assure la persistance et la synchronisation avec Firestore (server_credentials).
    """

    @staticmethod
    def get_secret(key: str) -> str:
        """
        Récupère un secret sécurisé.
        Tente d'abord de le lire dans le keyring Windows, sinon se replie sur les variables d'environnement / .env.
        Sur Cloud Run, vérifie également la collection server_credentials de Firestore.
        """
        if KEYRING_AVAILABLE:
            try:
                secret = keyring.get_password(SERVICE_NAME, key)
                if secret:
                    return secret
            except Exception:
                pass

        # Vérification Firestore sur Cloud Run
        global _FIRESTORE_SECRETS_CACHE, _FIRESTORE_SECRETS_LOADED
        is_cloud = bool(os.environ.get("K_SERVICE") or os.environ.get("K_CONFIGURATION"))
        if is_cloud and not _FIRESTORE_SECRETS_LOADED:
            _FIRESTORE_SECRETS_LOADED = True
            try:
                from infrastructure.firestore_client import FirestoreClient
                doc = FirestoreClient.get_document("server_credentials", "google_oauth")
                if doc:
                    _FIRESTORE_SECRETS_CACHE = doc
            except Exception:
                pass

        if _FIRESTORE_SECRETS_CACHE and key in ("GMAIL_REFRESH_TOKEN", "GMAIL_USER_EMAIL"):
            field_map = {"GMAIL_REFRESH_TOKEN": "refresh_token", "GMAIL_USER_EMAIL": "user_email"}
            target = field_map.get(key)
            if target and _FIRESTORE_SECRETS_CACHE.get(target):
                return str(_FIRESTORE_SECRETS_CACHE[target]).strip()

        # Repli sur le .env / Variables d'environnement
        return os.getenv(key, "").strip()

    @staticmethod
    def set_secret(key: str, value: str) -> bool:
        """
        Enregistre un secret de manière sécurisée.
        Tente de l'écrire dans le keyring Windows, et met également à jour le .env pour la persistance locale.
        Sur Cloud Run, synchronise avec Firestore (server_credentials).
        """
        success_keyring = False
        if KEYRING_AVAILABLE:
            try:
                keyring.set_password(SERVICE_NAME, key, value)
                success_keyring = True
            except Exception:
                pass

        # Persistance Firestore sur Cloud Run
        is_cloud = bool(os.environ.get("K_SERVICE") or os.environ.get("K_CONFIGURATION"))
        if is_cloud and key in ("GMAIL_REFRESH_TOKEN", "GMAIL_USER_EMAIL", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET"):
            field_map = {
                "GMAIL_REFRESH_TOKEN": "refresh_token",
                "GMAIL_USER_EMAIL": "user_email",
                "GMAIL_CLIENT_ID": "client_id",
                "GMAIL_CLIENT_SECRET": "client_secret",
            }
            target = field_map.get(key)
            if target:
                global _FIRESTORE_SECRETS_CACHE
                _FIRESTORE_SECRETS_CACHE[target] = value
                try:
                    from infrastructure.firestore_client import FirestoreClient
                    import datetime
                    FirestoreClient.update_fields(
                        "server_credentials",
                        "google_oauth",
                        {target: value, "updated_at": datetime.datetime.utcnow().isoformat()}
                    )
                except Exception:
                    pass
        
        # Enregistrement dans le .env pour assurer la persistance et la compatibilité historique
        # Racine du pack portable si un .env y vit déjà (survit aux mises à jour qui
        # ne remplacent que app/), sinon emplacement historique du code.
        try:
            root_env = os.path.join(ROOT_DIR, ".env")
            if getattr(sys, 'frozen', False) or os.path.exists(root_env):
                env_dir = ROOT_DIR
            else:
                env_dir = CODE_ROOT
            env_path = os.path.join(env_dir, ".env")
            lines = []
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            
            updated = False
            new_lines = []
            for line in lines:
                line_strip = line.strip()
                if line_strip and not line_strip.startswith("#") and "=" in line_strip:
                    k, v = line_strip.split("=", 1)
                    if k.strip() == key:
                        new_lines.append(f"{key}={value}\n")
                        updated = True
                        continue
                new_lines.append(line)
                
            if not updated:
                new_lines.append(f"{key}={value}\n")
                
            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            
            # Recharger os.environ
            os.environ[key] = value
            return True
        except Exception:
            return success_keyring
