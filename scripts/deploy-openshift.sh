#!/usr/bin/env bash
# One-command OpenShift deploy for an existing project namespace.
# INFERENCE=mock| rhaii|auto (default auto: RHAII CPU when HF + registry creds exist).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${1:-helpdesk-email-triage}"
INFERENCE="${INFERENCE:-auto}"
WAIT_TIMEOUT="${WAIT_TIMEOUT:-300s}"
RHAII_WAIT_TIMEOUT="${RHAII_WAIT_TIMEOUT:-900s}"

# shellcheck source=openshift-rhaii-secrets.sh
source "${ROOT}/scripts/openshift-rhaii-secrets.sh"
# shellcheck source=openshift-lib.sh
source "${ROOT}/scripts/openshift-lib.sh"

if ! command -v oc >/dev/null 2>&1; then
  echo "oc not found" >&2
  exit 1
fi
if ! command -v kustomize >/dev/null 2>&1; then
  echo "kustomize not found" >&2
  exit 1
fi

resolve_inference_mode() {
  case "$INFERENCE" in
    mock|rhaii) echo "$INFERENCE" ;;
    auto)
      if rhaii_prereqs_met "$NAMESPACE" >/dev/null 2>&1; then
        echo "rhaii"
      else
        echo "mock"
      fi
      ;;
    *)
      echo "Unknown INFERENCE=${INFERENCE} (use mock, rhaii, or auto)" >&2
      exit 1
      ;;
  esac
}

INFERENCE_MODE="$(resolve_inference_mode)"
resolve_deploy_overlay "$INFERENCE_MODE"
REQUESTED_OVERLAY="$RESOLVED_OVERLAY_REQUESTED"
OVERLAY="$RESOLVED_OVERLAY_APPLIED"

if [[ "$INFERENCE_MODE" == "rhaii" ]]; then
  WAIT_TIMEOUT="$RHAII_WAIT_TIMEOUT"
fi

if ! oc get namespace "$NAMESPACE" >/dev/null 2>&1; then
  oc new-project "$NAMESPACE"
fi
oc project "$NAMESPACE"

if [[ "$INFERENCE_MODE" == "rhaii" ]]; then
  rhaii_preflight "$NAMESPACE"
  echo "==> Preparing RHAII CPU secrets (registry.redhat.io + Hugging Face)"
  setup_rhaii_secrets "$NAMESPACE"
else
  if [[ "$INFERENCE" == "auto" ]]; then
    echo "==> Using mock inference (set HF_TOKEN and podman login registry.redhat.io for RHAII CPU)"
  fi
fi

echo "==> Applying ${OVERLAY} (inference=${INFERENCE_MODE}, image-tag=${IMAGE_TAG:-latest})"
openshift_kustomize_build "$OVERLAY" | oc apply -f -
record_deploy_metadata "$NAMESPACE" "$INFERENCE_MODE" "$REQUESTED_OVERLAY" "$OVERLAY"

echo "==> Waiting for deployments"
if [[ "$INFERENCE_MODE" == "rhaii" ]]; then
  oc wait deployment/rhaii-cpu -n "$NAMESPACE" --for=condition=Available --timeout="$WAIT_TIMEOUT"
fi
oc wait deployment/email-gateway deployment/agent-dashboard \
  -n "$NAMESPACE" --for=condition=Available --timeout="$WAIT_TIMEOUT"
if [[ "$INFERENCE_MODE" == "mock" ]]; then
  oc wait deployment/inference-mock -n "$NAMESPACE" --for=condition=Available --timeout="$WAIT_TIMEOUT"
fi

echo
echo "Deployed to namespace: ${NAMESPACE} (inference: ${INFERENCE_MODE})"
oc get pods,route -n "$NAMESPACE"

GW="$(oc get route email-gateway -n "$NAMESPACE" -o jsonpath='{.spec.host}')"
UI="$(oc get route agent-dashboard -n "$NAMESPACE" -o jsonpath='{.spec.host}')"
echo
echo "Gateway:   https://${GW}/health"
echo "Dashboard: https://${UI}"
if [[ "$INFERENCE_MODE" == "rhaii" ]]; then
  echo "Inference: RHAII CPU (registry.redhat.io/rhaii/vllm-cpu-rhel9) — first start may take several minutes"
fi
echo
echo "## Verify (hostname includes project name: ${NAMESPACE})"
echo "  make verify-openshift"
echo "  # or: ./scripts/openshift-verify.sh ${NAMESPACE}"
