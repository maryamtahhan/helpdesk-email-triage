#!/usr/bin/env bash
# Build images, load into kind, apply mock stack, run gateway smoke test, tear down.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=kind-lib.sh
source "${ROOT}/scripts/kind-lib.sh"

RECREATE_CLUSTER=1
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

echo "==> Ingesting sample email"
"${ROOT}/scripts/ingest-sample.sh" "${ROOT}/sample_emails/01-billing-double-charge.eml" >/dev/null

echo "==> Waiting for ticket"
for _ in $(seq 1 30); do
  count="$(curl -sf "${GATEWAY_URL}/tickets" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
  if [[ "${count}" -ge 1 ]]; then
    echo "==> Found ${count} ticket(s)"
    kubectl get pods -n "$NAMESPACE"
    exit 0
  fi
  sleep 2
done

echo "No tickets appeared after ingest" >&2
kubectl get pods -n "$NAMESPACE"
exit 1
