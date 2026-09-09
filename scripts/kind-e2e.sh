#!/usr/bin/env bash
# Build images, load into kind, apply mock stack, run gateway smoke test, tear down.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=kind-lib.sh
source "${ROOT}/scripts/kind-lib.sh"

GATEWAY_URL="http://127.0.0.1:8080"

kind_ensure_tools
kind_ensure_cluster
kind_build_and_load_images
kind_apply_stack

echo "==> Port-forwarding email-gateway"
kubectl port-forward -n "$NAMESPACE" svc/email-gateway 8080:8080 >/tmp/helpdesk-kind-pf.log 2>&1 &
PF_PID=$!
sleep 3

stop_pf() {
  kill "$PF_PID" >/dev/null 2>&1 || true
  wait "$PF_PID" 2>/dev/null || true
}

cleanup_e2e() {
  stop_pf
  "${ROOT}/scripts/destroy-kind.sh"
}
trap cleanup_e2e EXIT

echo "==> Checking gateway health"
curl -sf "${GATEWAY_URL}/health" >/dev/null

echo "==> Waiting for ticket (file watcher on sample_emails/)"
if count="$("${ROOT}/scripts/wait-for-tickets.sh" 30 2)"; then
  echo "==> Found ${count} ticket(s)"
  kubectl get pods -n "$NAMESPACE"
  exit 0
fi

echo "==> No file-watcher tickets yet; ingesting via /ingest/raw"
curl -sf -X POST "${GATEWAY_URL}/ingest/raw" \
  -H "Content-Type: application/json" \
  -d '{"sender":"ci@example.com","subject":"CI smoke","body":"Charged twice on card ACC-998877."}' >/dev/null

echo "==> Waiting for ticket"
export GATEWAY_URL
if count="$("${ROOT}/scripts/wait-for-tickets.sh" 15 2)"; then
  echo "==> Found ${count} ticket(s)"
  kubectl get pods -n "$NAMESPACE"
  exit 0
fi

echo "No tickets appeared after ingest" >&2
kubectl get pods -n "$NAMESPACE"
exit 1
