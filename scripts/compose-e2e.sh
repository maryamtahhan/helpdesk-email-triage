#!/usr/bin/env bash
# End-to-end smoke test: compose stack up → health → ingest → ticket list → down.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-compose.gateway-only.yml}"
COMPOSE=(docker compose -f "${ROOT}/${COMPOSE_FILE}")

if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  COMPOSE=(podman compose -f "${ROOT}/${COMPOSE_FILE}")
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

echo "==> Ingesting sample email"
"${ROOT}/scripts/ingest-sample.sh" "${ROOT}/sample_emails/01-billing-double-charge.eml" >/dev/null

echo "==> Waiting for ticket"
for _ in $(seq 1 30); do
  count="$(curl -sf "${GATEWAY_URL}/tickets" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
  if [[ "${count}" -ge 1 ]]; then
    echo "==> Found ${count} ticket(s)"
    exit 0
  fi
  sleep 2
done

echo "No tickets appeared after ingest" >&2
exit 1
