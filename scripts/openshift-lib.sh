#!/usr/bin/env bash
# Shared helpers for OpenShift deploy/undeploy scripts.
set -euo pipefail

openshift_kustomize_build() {
  local overlay="$1"
  local tag="${IMAGE_TAG:-latest}"
  if [[ "$tag" == "latest" ]]; then
    kustomize build --load-restrictor LoadRestrictionsNone "$overlay"
    return 0
  fi

  local tmp
  tmp="$(mktemp -d)"
  cp -R "$overlay/." "$tmp/"
  (
    cd "$tmp"
    kustomize edit set image \
      "quay.io/mtahhan/helpdesk-email-gateway=quay.io/mtahhan/helpdesk-email-gateway:${tag}" \
      "quay.io/mtahhan/helpdesk-triage-ui=quay.io/mtahhan/helpdesk-triage-ui:${tag}" \
      "quay.io/mtahhan/helpdesk-inference-mock=quay.io/mtahhan/helpdesk-inference-mock:${tag}"
    kustomize build --load-restrictor LoadRestrictionsNone .
  )
  rm -rf "$tmp"
}

record_deploy_metadata() {
  local namespace="$1"
  local inference_mode="$2"
  local overlay="$3"
  oc create configmap helpdesk-deploy-info \
    --from-literal=inference-mode="$inference_mode" \
    --from-literal=overlay="$overlay" \
    --from-literal=image-tag="${IMAGE_TAG:-latest}" \
    -n "$namespace" \
    --dry-run=client -o yaml | oc apply -f -
}

read_deploy_metadata() {
  local namespace="$1"
  if ! oc get configmap helpdesk-deploy-info -n "$namespace" >/dev/null 2>&1; then
    return 1
  fi
  DEPLOY_INFERENCE_MODE="$(oc get configmap helpdesk-deploy-info -n "$namespace" -o jsonpath='{.data.inference-mode}')"
  DEPLOY_OVERLAY="$(oc get configmap helpdesk-deploy-info -n "$namespace" -o jsonpath='{.data.overlay}')"
  DEPLOY_IMAGE_TAG="$(oc get configmap helpdesk-deploy-info -n "$namespace" -o jsonpath='{.data.image-tag}')"
}

rhaii_preflight() {
  local namespace="$1"
  echo "==> Checking cluster capacity for RHAII CPU (requests: 4 CPU, 8Gi memory)"
  if python3 - <<'PY'
import json, subprocess, sys

min_gi = 16
raw = subprocess.check_output(["oc", "get", "nodes", "-o", "json"], text=True)
data = json.loads(raw)
for node in data.get("items", []):
    mem = node.get("status", {}).get("allocatable", {}).get("memory", "0")
    if mem.endswith("Ki"):
        gi = int(mem[:-2]) / (1024 ** 2)
        if gi >= min_gi:
            sys.exit(0)
sys.exit(1)
PY
  then
    echo "    Found node(s) with >=16Gi allocatable memory"
    return 0
  fi

  echo "WARNING: No node with >=16Gi allocatable memory. rhaii-cpu may stay Pending." >&2
  echo "         See docs/deploy-openshift.md for sizing guidance." >&2
  if [[ "${FAIL_ON_RHAII_PREFLIGHT:-0}" == "1" ]]; then
    return 1
  fi
}
