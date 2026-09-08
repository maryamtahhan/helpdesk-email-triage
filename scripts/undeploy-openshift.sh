#!/usr/bin/env bash
# Remove helpdesk resources from an OpenShift project.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${1:-helpdesk-email-triage}"
INFERENCE="${INFERENCE:-auto}"
DELETE_NAMESPACE="${DELETE_NAMESPACE:-0}"

# shellcheck source=openshift-rhaii-secrets.sh
source "${ROOT}/scripts/openshift-rhaii-secrets.sh"

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
      if oc get deployment rhaii-cpu -n "$NAMESPACE" >/dev/null 2>&1; then
        echo "rhaii"
      else
        echo "mock"
      fi
      ;;
    *)
      echo "Unknown INFERENCE=${INFERENCE}" >&2
      exit 1
      ;;
  esac
}

resolve_overlay() {
  local mode="$1"
  if [[ -n "${OVERLAY:-}" ]]; then
    echo "$OVERLAY"
    return 0
  fi
  case "$mode" in
    rhaii) echo "${ROOT}/deploy/openshift/overlays/helpdesk-email-triage-rhaii" ;;
    mock) echo "${ROOT}/deploy/openshift/overlays/helpdesk-email-triage" ;;
  esac
}

if [[ "$DELETE_NAMESPACE" == "1" ]]; then
  echo "==> Deleting OpenShift project ${NAMESPACE}"
  oc delete project "$NAMESPACE" --ignore-not-found
  echo "Project deleted."
  exit 0
fi

if ! oc get namespace "$NAMESPACE" >/dev/null 2>&1; then
  echo "Namespace ${NAMESPACE} does not exist; nothing to undeploy."
  exit 0
fi

oc project "$NAMESPACE"
INFERENCE_MODE="$(resolve_inference_mode)"
OVERLAY="$(resolve_overlay "$INFERENCE_MODE")"

echo "==> Removing resources from ${OVERLAY} (inference=${INFERENCE_MODE})"
kustomize build --load-restrictor LoadRestrictionsNone "$OVERLAY" | oc delete -f - --ignore-not-found

echo
echo "Removed helpdesk resources from ${NAMESPACE}."
echo "The project still exists. To delete it entirely:"
echo "  DELETE_NAMESPACE=1 make undeploy-openshift"
echo "  # or: oc delete project ${NAMESPACE}"
