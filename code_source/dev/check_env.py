"""
Garde-fou du mode dev, exécuté par dev/run_server.sh avant le serveur.

Vérifie la configuration EFFECTIVE telle que l'application la verra : `SecretStore` est
importé comme dans le serveur, donc avec le chargement des fichiers .env (dont
`<dépôt>/.env` en override=True, qui pourrait écraser dev/dev.env). Refuse de démarrer
si un e-mail pouvait partir pour de vrai (API Gmail active ou SMTP autre que Mailpit
en local) ou si l'émulateur Firebase n'est pas configuré.
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from infrastructure import runtime_env  # noqa: E402
from infrastructure.secret_store import SecretStore  # noqa: E402  (charge les .env comme l'application)

LOCAL_SMTP_HOSTS = {"localhost", "127.0.0.1", "::1"}


def problems() -> list:
    found = []
    try:
        runtime_env.validate()
    except RuntimeError as e:
        found.append(str(e))
    if not runtime_env.is_dev():
        found.append("ALJ_ENV n'est pas « dev » (un fichier .env l'a-t-il écrasé ?).")

    gmail = [k for k in ("GMAIL_USER_EMAIL", "GMAIL_CLIENT_ID", "GMAIL_REFRESH_TOKEN") if SecretStore.get_secret(k)]
    if len(gmail) == 3:
        found.append("API Gmail active (GMAIL_USER_EMAIL / GMAIL_CLIENT_ID / GMAIL_REFRESH_TOKEN définis, "
                     "probablement par un fichier .env) : les e-mails partiraient réellement.")

    smtp_host = SecretStore.get_secret("SMTP_HOST")
    if smtp_host.lower() not in LOCAL_SMTP_HOSTS:
        found.append(f"SMTP_HOST={smtp_host or '(vide)'} : le mode dev n'envoie que vers Mailpit en local.")
    return found


def main() -> int:
    found = problems()
    if found:
        print("❌ Configuration dev refusée :", file=sys.stderr)
        for p in found:
            print(f"   - {p}", file=sys.stderr)
        print("   Vérifiez code_source/.env et le .env à la racine du dépôt (ils priment sur dev/dev.env).",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
