#!/usr/bin/env bash
# End-to-end smoke test: compose stack up → health → ticket list → down.
# Uses compose.gateway-only.yml (inference-mock), not compose.yml (real RHAII).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-compose.gateway-only.yml}"

compose_engine_ready() {
  local engine="$1"
  command -v "$engine" >/dev/null 2>&1 \
    && "$engine" info >/dev/null 2>&1 \
    && "$engine" compose version >/dev/null 2>&1
}

if [[ -n "${COMPOSE_ENGINE:-}" ]]; then
  if ! compose_engine_ready "${COMPOSE_ENGINE}"; then
    echo "${COMPOSE_ENGINE} compose is not available" >&2
    exit 1
  fi
  COMPOSE=("${COMPOSE_ENGINE}" compose -f "${ROOT}/${COMPOSE_FILE}")
elif compose_engine_ready docker; then
  COMPOSE=(docker compose -f "${ROOT}/${COMPOSE_FILE}")
elif compose_engine_ready podman; then
  COMPOSE=(podman compose -f "${ROOT}/${COMPOSE_FILE}")
else
  echo "Neither docker nor podman compose is available" >&2
  exit 1
fi

cleanup() {
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> Starting stack (${COMPOSE_FILE})"
"${COMPOSE[@]}" up -d --build

GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"

echo "==> Waiting for gateway health"
for _ in $(seq 1 60); do
  if curl -sf "${GATEWAY_URL}/health" >/dev/null; then
    break
  fi
  sleep 2
done
curl -sf "${GATEWAY_URL}/health" >/dev/null

echo "==> Waiting for ticket (file watcher on sample_emails/)"
if count="$("${ROOT}/scripts/wait-for-tickets.sh" 30 2)"; then
  echo "==> Found ${count} ticket(s)"
  exit 0
fi

echo "==> No file-watcher tickets yet; ingesting via /ingest/raw"
curl -sf -X POST "${GATEWAY_URL}/ingest/raw" \
  -H "Content-Type: application/json" \
  -d '{"sender":"ci@example.com","subject":"CI smoke","body":"Charged twice on card ACC-998877."}' >/dev/null

if count="$("${ROOT}/scripts/wait-for-tickets.sh" 15 2)"; then
  echo "==> Found ${count} ticket(s)"
  exit 0
fi

echo "No tickets appeared after ingest" >&2
exit 1
