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

class SecretStore:
    """
    Gère le stockage et la récupération sécurisée des secrets d'authentification.
    Tente d'utiliser le trousseau d'accès Windows via 'keyring' et se replie sur le fichier '.env'.
    """

    @staticmethod
    def get_secret(key: str) -> str:
        """
        Récupère un secret sécurisé.
        Tente d'abord de le lire dans le keyring Windows, sinon se replie sur les variables d'environnement / .env.
        """
        if KEYRING_AVAILABLE:
            try:
                secret = keyring.get_password(SERVICE_NAME, key)
                if secret:
                    return secret
            except Exception:
                pass
        
        # Repli sur le .env / Variables d'environnement
        return os.getenv(key, "").strip()

    @staticmethod
    def set_secret(key: str, value: str) -> bool:
        """
        Enregistre un secret de manière sécurisée.
        Tente de l'écrire dans le keyring Windows, et met également à jour le .env pour la persistance locale.
        """
        success_keyring = False
        if KEYRING_AVAILABLE:
            try:
                keyring.set_password(SERVICE_NAME, key, value)
                success_keyring = True
            except Exception:
                pass
        
        # Enregistrement dans le .env pour assurer la persistance et la compatibilité historique
        try:
            env_dir = ROOT_DIR if getattr(sys, 'frozen', False) else CODE_ROOT
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
