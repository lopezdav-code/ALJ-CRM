#!/usr/bin/env bash
# Starts the FastAPI server in dev mode, connected to the local Firebase emulator.
set -euo pipefail
cd "$(dirname "$0")/.."            # code_source/

set -a; source dev/dev.env; set +a

if ! curl -sf "http://${FIRESTORE_EMULATOR_HOST}/" >/dev/null; then
  echo "❌ Firestore emulator unreachable at ${FIRESTORE_EMULATOR_HOST}." >&2
  echo "   Run: docker compose -f dev/docker-compose.yml up -d" >&2
  exit 1
fi

if ! curl -sf "http://localhost:8025/" >/dev/null; then
  echo "❌ Mailpit (e-mail capture) unreachable at localhost:8025." >&2
  echo "   Run: docker compose -f dev/docker-compose.yml up -d" >&2
  exit 1
fi

# Effective configuration (including .env files): no real e-mail, emulator required
python dev/check_env.py

PORT="${PORT:-8080}"
echo "🧪 DEV mode (emulator) → http://localhost:${PORT}/bureau/"
exec uvicorn server:app --app-dir src --host 127.0.0.1 --port "${PORT}" \
  --reload --reload-dir src "$@"
