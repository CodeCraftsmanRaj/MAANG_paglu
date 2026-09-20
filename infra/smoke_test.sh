#!/usr/bin/env bash
# Smoke-test a deployed ContextForge API.
#   ./smoke_test.sh https://xxxx.execute-api.us-east-1.amazonaws.com
#
# On a FRESH stack the FIRST registered account becomes admin. This script registers
# one — control it with env vars so you keep a memorable admin:
#   SMOKE_USER=myadmin SMOKE_PASS=SuperSecret1! ./smoke_test.sh <url>
# Or run the full flow against an account you already registered:
#   SMOKE_TOKEN=<bearer-token> ./smoke_test.sh <url>
set -euo pipefail

BASE="${1:?Usage: ./smoke_test.sh <api-url>}"
BASE="${BASE%/}"
USER_NAME="${SMOKE_USER:-smoke_$RANDOM}"
PASS="${SMOKE_PASS:-FirstCommit1!}"

echo "==> 1. GET /api/status"
curl -fsS "$BASE/api/status"
echo; echo

if [ -n "${SMOKE_TOKEN:-}" ]; then
  echo "==> 2. Using provided SMOKE_TOKEN (skipping registration)"
  TOKEN="$SMOKE_TOKEN"
else
  echo "==> 2. Registering '$USER_NAME' (first account = admin on a fresh stack)"
  REG=$(curl -fsS -X POST "$BASE/api/auth/register" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"$USER_NAME\",\"password\":\"$PASS\"}")
  echo "$REG"
  TOKEN=$(echo "$REG" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
  echo
fi

echo "==> 3. Creating a project"
PROJ=$(curl -fsS -X POST "$BASE/api/projects" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"Deploy Smoke Test","project_type":"general"}')
echo "$PROJ"
PID=$(echo "$PROJ" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')
echo

echo "==> 4. Ingesting a fact (extraction + Titan embedding via Bedrock)"
curl -fsS -X POST "$BASE/api/ingest" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"kind\":\"text\",\"title\":\"Smoke note\",\"text\":\"The production API timeout is 29 seconds behind API Gateway. The database port is 5432.\",\"project_id\":\"$PID\"}"
echo; echo

echo "==> 5. Asking a question (Bedrock Claude synthesis)"
curl -fsS -X POST "$BASE/api/ask" \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"query\":\"What is the production API timeout?\",\"project_id\":\"$PID\"}"
echo; echo

echo "✅ Smoke test complete."
