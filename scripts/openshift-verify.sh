#!/usr/bin/env bash
# Print OpenShift Route URLs for the helpdesk stack and optionally run smoke checks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

GATEWAY_URL="https://${GW}"
INGEST_API_KEY="$(oc get secret helpdesk-secrets -n "$NAMESPACE" -o jsonpath='{.data.INGEST_API_KEY}' 2>/dev/null | base64 -d 2>/dev/null || true)"

echo "Namespace: ${NAMESPACE}"
echo "Gateway:   ${GATEWAY_URL}/health"
echo "Dashboard: https://${UI}"
echo
echo "## Verify"
echo "curl -sk \"${GATEWAY_URL}/health\""
echo "curl -skI \"https://${UI}\" | head -5"
echo "Open: https://${UI}"

if [[ "$RUN_CHECKS" != "1" ]]; then
  exit 0
fi

echo
echo "==> Gateway health"
curl -sk "${GATEWAY_URL}/health"
echo
echo
echo "==> Dashboard headers"
curl -skI "https://${UI}" | head -5

echo
echo "==> Waiting for ticket (file watcher on sample_emails/)"
export GATEWAY_URL
if count="$("${ROOT}/scripts/wait-for-tickets.sh" 30 2)"; then
  echo "==> Found ${count} ticket(s) from file watcher"
  exit 0
fi

echo "==> No file-watcher tickets yet; ingesting via /ingest/raw"
INGEST_HEADERS=(-H "Content-Type: application/json")
if [[ -n "$INGEST_API_KEY" ]]; then
  INGEST_HEADERS+=(-H "X-Ingest-Key: ${INGEST_API_KEY}")
fi
curl -sk -X POST "${GATEWAY_URL}/ingest/raw" \
  "${INGEST_HEADERS[@]}" \
  -d '{"sender":"verify@example.com","subject":"OpenShift verify","body":"Charged twice on card ACC-998877."}' >/dev/null

if count="$("${ROOT}/scripts/wait-for-tickets.sh" 15 2)"; then
  echo "==> Found ${count} ticket(s) after ingest"
  exit 0
fi

echo "No tickets appeared after ingest" >&2
exit 1
