#!/usr/bin/env bash
# Print OpenShift Route URLs for the helpdesk stack and optionally run smoke checks.
set -euo pipefail

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

echo "Namespace: ${NAMESPACE}"
echo "Gateway:   https://${GW}/health"
echo "Dashboard: https://${UI}"
echo
echo "## Verify"
echo "curl -sk \"https://${GW}/health\""
echo "curl -skI \"https://${UI}\" | head -5"
echo "Open: https://${UI}"

if [[ "$RUN_CHECKS" != "1" ]]; then
  exit 0
fi

echo
echo "==> Gateway health"
curl -sk "https://${GW}/health"
echo
echo
echo "==> Dashboard headers"
curl -skI "https://${UI}" | head -5
