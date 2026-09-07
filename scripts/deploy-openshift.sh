#!/usr/bin/env bash
# One-command OpenShift deploy for an existing project namespace.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${1:-helpdesk-email-triage}"
OVERLAY="${OVERLAY:-${ROOT}/deploy/openshift/overlays/helpdesk-email-triage}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-300s}"

if ! command -v oc >/dev/null 2>&1; then
  echo "oc not found" >&2
  exit 1
fi
if ! command -v kustomize >/dev/null 2>&1; then
  echo "kustomize not found" >&2
  exit 1
fi

if ! oc get namespace "$NAMESPACE" >/dev/null 2>&1; then
  oc new-project "$NAMESPACE"
fi
oc project "$NAMESPACE"

echo "==> Applying ${OVERLAY}"
kustomize build --load-restrictor LoadRestrictionsNone "$OVERLAY" | oc apply -f -

echo "==> Waiting for deployments"
oc wait deployment/inference-mock deployment/email-gateway deployment/agent-dashboard \
  -n "$NAMESPACE" --for=condition=Available --timeout="$WAIT_TIMEOUT"

echo
echo "Deployed to namespace: ${NAMESPACE}"
oc get pods,route -n "$NAMESPACE"

GW="$(oc get route email-gateway -n "$NAMESPACE" -o jsonpath='{.spec.host}')"
UI="$(oc get route agent-dashboard -n "$NAMESPACE" -o jsonpath='{.spec.host}')"
echo
echo "Gateway:   https://${GW}/health"
echo "Dashboard: https://${UI}"
echo
echo "## Verify"
echo "curl -sk https://${GW}/health"
echo "curl -skI https://${UI} | head -5"
echo "Open: https://${UI}"
