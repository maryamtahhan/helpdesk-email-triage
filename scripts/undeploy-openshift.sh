#!/usr/bin/env bash
# Remove helpdesk resources from an OpenShift project.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${1:-helpdesk-email-triage}"
OVERLAY="${OVERLAY:-${ROOT}/deploy/openshift/overlays/helpdesk-email-triage}"
DELETE_NAMESPACE="${DELETE_NAMESPACE:-0}"

if ! command -v oc >/dev/null 2>&1; then
  echo "oc not found" >&2
  exit 1
fi
if ! command -v kustomize >/dev/null 2>&1; then
  echo "kustomize not found" >&2
  exit 1
fi

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

echo "==> Removing resources from ${OVERLAY}"
kustomize build --load-restrictor LoadRestrictionsNone "$OVERLAY" | oc delete -f - --ignore-not-found

echo
echo "Removed helpdesk resources from ${NAMESPACE}."
echo "The project still exists. To delete it entirely:"
echo "  DELETE_NAMESPACE=1 make undeploy-openshift"
echo "  # or: oc delete project ${NAMESPACE}"
