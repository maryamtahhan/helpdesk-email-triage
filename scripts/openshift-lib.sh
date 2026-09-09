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

  # Copy overlay to a temp dir so `kustomize edit set image` does not mutate the tree.
  # Symlinks under the overlay are not preserved; use absolute paths in kustomization if needed.
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  cp -R "$overlay/." "$tmp/"
  (
    cd "$tmp"
    kustomize edit set image \
      "quay.io/mtahhan/helpdesk-email-gateway=quay.io/mtahhan/helpdesk-email-gateway:${tag}" \
      "quay.io/mtahhan/helpdesk-triage-ui=quay.io/mtahhan/helpdesk-triage-ui:${tag}" \
      "quay.io/mtahhan/helpdesk-inference-mock=quay.io/mtahhan/helpdesk-inference-mock:${tag}"
    kustomize build --load-restrictor LoadRestrictionsNone .
  )
}

resolve_overlay_path() {
  local path="$1"
  if [[ "$path" != /* ]]; then
    path="${ROOT}/${path}"
  fi
  echo "$path"
}

overlay_inference_mode() {
  local path="$1"
  case "$path" in
    *external-inference*|*gateway-only*) echo "skip" ;;
    *helpdesk-email-triage-rhaii*|*hardened-rhaii*|*rhaii-demo*) echo "rhaii" ;;
    *) echo "mock" ;;
  esac
}

validate_overlay_inference() {
  local mode="$1"
  local path="$2"
  local expected
  expected="$(overlay_inference_mode "$path")"
  if [[ "$expected" == "skip" ]]; then
    return 0
  fi
  if [[ "$mode" != "$expected" ]]; then
    echo "ERROR: INFERENCE=${mode} conflicts with overlay (expects ${expected}):" >&2
    echo "       ${path}" >&2
    echo "       Use INFERENCE=${expected} or choose a matching overlay." >&2
    exit 1
  fi
}

# Sets RESOLVED_OVERLAY_REQUESTED and RESOLVED_OVERLAY_APPLIED (absolute paths).
resolve_deploy_overlay() {
  local mode="$1"
  local requested=""
  local applied=""

  if [[ -n "${OVERLAY:-}" ]]; then
    requested="$(resolve_overlay_path "$OVERLAY")"
    applied="$requested"
    if [[ "$requested" == "${ROOT}/deploy/openshift/overlays/hardened" && "$mode" == "rhaii" ]]; then
      applied="${ROOT}/deploy/openshift/overlays/hardened-rhaii"
      echo "==> Remapping OVERLAY: hardened -> hardened-rhaii (INFERENCE=rhaii)" >&2
    fi
  else
    case "$mode" in
      rhaii) applied="${ROOT}/deploy/openshift/overlays/helpdesk-email-triage-rhaii" ;;
      mock) applied="${ROOT}/deploy/openshift/overlays/helpdesk-email-triage" ;;
    esac
    requested="$applied"
  fi

  validate_overlay_inference "$mode" "$applied"
  export RESOLVED_OVERLAY_REQUESTED="$requested"
  export RESOLVED_OVERLAY_APPLIED="$applied"
}

record_deploy_metadata() {
  local namespace="$1"
  local inference_mode="$2"
  local requested_overlay="$3"
  local applied_overlay="$4"
  oc create configmap helpdesk-deploy-info \
    --from-literal=inference-mode="$inference_mode" \
    --from-literal=overlay="$requested_overlay" \
    --from-literal=applied-overlay="$applied_overlay" \
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
  DEPLOY_APPLIED_OVERLAY="$(oc get configmap helpdesk-deploy-info -n "$namespace" -o jsonpath='{.data.applied-overlay}')"
  if [[ -z "$DEPLOY_APPLIED_OVERLAY" ]]; then
    DEPLOY_APPLIED_OVERLAY="$DEPLOY_OVERLAY"
  fi
  DEPLOY_IMAGE_TAG="$(oc get configmap helpdesk-deploy-info -n "$namespace" -o jsonpath='{.data.image-tag}')"
  export DEPLOY_INFERENCE_MODE DEPLOY_OVERLAY DEPLOY_APPLIED_OVERLAY DEPLOY_IMAGE_TAG
}

# True when the gateway Route is protected by OpenShift OAuth (hardened overlays).
openshift_gateway_route_oauth() {
  local namespace="$1"
  local oauth
  oauth="$(oc get route email-gateway -n "$namespace" \
    -o jsonpath='{.metadata.annotations.haproxy\.router\.openshift\.io/oauth-expose}' 2>/dev/null || true)"
  [[ "$oauth" == "true" ]]
}

# Start a local port-forward to svc/email-gateway; prints PID on stdout.
openshift_gateway_port_forward() {
  local namespace="$1"
  local local_port="${2:-18080}"
  oc port-forward -n "$namespace" "svc/email-gateway" "${local_port}:8080" >/dev/null 2>&1 &
  echo $!
}

openshift_gateway_readiness_hint() {
  local namespace="$1"
  if ! oc get deployment email-gateway -n "$namespace" >/dev/null 2>&1; then
    return 0
  fi
  local ready
  ready="$(oc get deployment email-gateway -n "$namespace" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)"
  if [[ "${ready:-0}" == "1" ]]; then
    return 0
  fi
  if oc logs deployment/email-gateway -n "$namespace" --tail=30 2>/dev/null \
    | grep -q 'GET /health/ready HTTP/1.1" 404'; then
    echo "WARNING: email-gateway is not Ready — the running image lacks GET /health/ready." >&2
    echo "         Rebuild and push quay.io/mtahhan/helpdesk-email-gateway:latest, then:" >&2
    echo "           oc rollout restart deployment/email-gateway -n ${namespace}" >&2
    echo "         Quick workaround (readiness on /health only):" >&2
    echo '           oc patch deployment email-gateway -n '"${namespace}"' --type=json -p='"'"'[{"op":"replace","path":"/spec/template/spec/containers/0/readinessProbe/httpGet/path","value":"/health"}]'"'" >&2
  fi
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
