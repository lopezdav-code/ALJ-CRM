"""
Dev mode safeguard, run by dev/run_server.sh before the server.

Checks the EFFECTIVE configuration as the application will see it: `SecretStore` is
imported as the server does, so the .env files are loaded too (including `<repo>/.env`
with override=True, which could override dev/dev.env). Refuses to start if an e-mail
could really be sent (Gmail API enabled or SMTP other than the local Mailpit) or if the
Firebase emulator is not configured.
"""
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from infrastructure import runtime_env  # noqa: E402
from infrastructure.secret_store import SecretStore  # noqa: E402  (loads the .env files like the application)

LOCAL_SMTP_HOSTS = {"localhost", "127.0.0.1", "::1"}


def problems() -> list:
    found = []
    try:
        runtime_env.validate()
    except RuntimeError as e:
        found.append(str(e))
    if not runtime_env.is_dev():
        found.append("ALJ_ENV is not \"dev\" (was it overridden by a .env file?).")

    gmail = [k for k in ("GMAIL_USER_EMAIL", "GMAIL_CLIENT_ID", "GMAIL_REFRESH_TOKEN") if SecretStore.get_secret(k)]
    if len(gmail) == 3:
        found.append("Gmail API enabled (GMAIL_USER_EMAIL / GMAIL_CLIENT_ID / GMAIL_REFRESH_TOKEN set, "
                     "probably by a .env file): e-mails would really be sent.")

    smtp_host = SecretStore.get_secret("SMTP_HOST")
    if smtp_host.lower() not in LOCAL_SMTP_HOSTS:
        found.append(f"SMTP_HOST={smtp_host or '(empty)'}: dev mode only sends to the local Mailpit.")
    return found


def main() -> int:
    found = problems()
    if found:
        print("❌ Dev configuration rejected:", file=sys.stderr)
        for p in found:
            print(f"   - {p}", file=sys.stderr)
        print("   Check code_source/.env and the .env at the repository root (they take precedence over dev/dev.env).",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
