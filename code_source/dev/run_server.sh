#!/usr/bin/env bash
# Lance le serveur FastAPI en mode dev, branché sur l'émulateur Firebase local.
set -euo pipefail
cd "$(dirname "$0")/.."            # code_source/

set -a; source dev/dev.env; set +a

if ! curl -sf "http://${FIRESTORE_EMULATOR_HOST}/" >/dev/null; then
  echo "❌ Émulateur Firestore injoignable sur ${FIRESTORE_EMULATOR_HOST}." >&2
  echo "   Lancez : docker compose -f dev/docker-compose.yml up -d" >&2
  exit 1
fi

if ! curl -sf "http://localhost:8025/" >/dev/null; then
  echo "❌ Mailpit (capture des e-mails) injoignable sur localhost:8025." >&2
  echo "   Lancez : docker compose -f dev/docker-compose.yml up -d" >&2
  exit 1
fi

# Configuration effective (fichiers .env compris) : aucun e-mail réel, émulateur obligatoire
python dev/check_env.py

PORT="${PORT:-8080}"
echo "🧪 Mode DEV (émulateur) → http://localhost:${PORT}/bureau/"
exec uvicorn server:app --app-dir src --host 127.0.0.1 --port "${PORT}" \
  --reload --reload-dir src "$@"
