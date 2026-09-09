#!/usr/bin/env bash
# Print OpenShift Route URLs for the helpdesk stack and optionally run smoke checks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=openshift-lib.sh
source "${ROOT}/scripts/openshift-lib.sh"
NAMESPACE="${1:-helpdesk-email-triage}"
RUN_CHECKS="${RUN_CHECKS:-1}"

if ! command -v oc >/dev/null 2>&1; then
  echo "oc not found" >&2
  exit 1
fi

if ! oc get namespace "$NAMESPACE" >/dev/null 2>&1; then
  echo "Namespace ${NAMESPACE} not found." >&2
  exit 1
fi

GW="$(oc get route email-gateway -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || true)"
UI="$(oc get route agent-dashboard -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || true)"

if [[ -z "$GW" || -z "$UI" ]]; then
  echo "Routes not found in namespace ${NAMESPACE}. Run make deploy-openshift first." >&2
  oc get route -n "$NAMESPACE" 2>/dev/null || true
  exit 1
fi

GATEWAY_ROUTE_URL="https://${GW}"
INGEST_API_KEY="$(oc get secret helpdesk-secrets -n "$NAMESPACE" -o jsonpath='{.data.INGEST_API_KEY}' 2>/dev/null | base64 -d 2>/dev/null || true)"

echo "Namespace: ${NAMESPACE}"
echo "Gateway:   ${GATEWAY_ROUTE_URL}/health"
echo "Dashboard: https://${UI}"
if openshift_gateway_route_oauth "$NAMESPACE"; then
  echo "Note:      Gateway Route is OAuth-protected; API smoke tests use in-cluster port-forward."
fi
echo
echo "## Verify"
echo "curl -sk \"${GATEWAY_ROUTE_URL}/health\"   # may show OAuth page when hardened"
echo "curl -skI \"https://${UI}\" | head -5"
echo "Open: https://${UI}"

if [[ "$RUN_CHECKS" != "1" ]]; then
  exit 0
fi

GATEWAY_URL="$GATEWAY_ROUTE_URL"
PF_PID=""
if openshift_gateway_route_oauth "$NAMESPACE"; then
  PF_PID="$(openshift_gateway_port_forward "$NAMESPACE" 18080)"
  sleep 2
  GATEWAY_URL="http://127.0.0.1:18080"
  trap 'kill "${PF_PID}" 2>/dev/null || true' EXIT
fi

echo
echo "==> Gateway health (API base: ${GATEWAY_URL})"
if ! health_body="$(curl -sf "${GATEWAY_URL}/health")"; then
  openshift_gateway_readiness_hint "$NAMESPACE"
  echo "Gateway /health failed" >&2
  exit 1
fi
echo "$health_body"

if ! curl -sf "${GATEWAY_URL}/health/ready" >/dev/null 2>&1; then
  echo
  echo "==> Gateway /health/ready not available (published image may be stale)"
  openshift_gateway_readiness_hint "$NAMESPACE"
fi

echo
echo "==> Dashboard headers"
curl -skI "https://${UI}" | head -5

echo
echo "==> Waiting for ticket (file watcher on sample_emails/)"
export GATEWAY_URL
export INGEST_API_KEY
if count="$("${ROOT}/scripts/wait-for-tickets.sh" 30 2)"; then
  echo "==> Found ${count} ticket(s) from file watcher"
  exit 0
fi

echo "==> No file-watcher tickets yet; ingesting via /ingest/raw"
INGEST_HEADERS=(-H "Content-Type: application/json")
if [[ -n "$INGEST_API_KEY" ]]; then
  INGEST_HEADERS+=(-H "X-Ingest-Key: ${INGEST_API_KEY}")
fi
if ! curl -sf -X POST "${GATEWAY_URL}/ingest/raw" \
  "${INGEST_HEADERS[@]}" \
  -d '{"sender":"verify@example.com","subject":"OpenShift verify","body":"Charged twice on card ACC-998877."}' >/dev/null; then
  echo "Ingest failed (check INGEST_API_KEY and gateway logs)" >&2
  exit 1
fi

if count="$("${ROOT}/scripts/wait-for-tickets.sh" 15 2)"; then
  echo "==> Found ${count} ticket(s) after ingest"
  exit 0
fi

echo "No tickets appeared after ingest" >&2
exit 1
