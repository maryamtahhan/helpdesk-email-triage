#!/usr/bin/env bash
# Build images, load into kind, apply mock stack, run gateway smoke test.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${KIND_CLUSTER_NAME:-helpdesk-ci}"
NAMESPACE="${KIND_NAMESPACE:-helpdesk-kind-test}"
OVERLAY="${OVERLAY:-${ROOT}/deploy/kind/overlays/mock-demo}"
KEEP_CLUSTER="${KEEP_CLUSTER:-0}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "$1 not found" >&2
    exit 1
  }
}

need docker
need kind
need kubectl
need kustomize

cleanup() {
  if [[ "$KEEP_CLUSTER" != "1" ]]; then
    kind delete cluster --name "$CLUSTER_NAME" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "==> Creating kind cluster ${CLUSTER_NAME}"
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  kind delete cluster --name "$CLUSTER_NAME"
fi
kind create cluster --name "$CLUSTER_NAME" --config "${ROOT}/deploy/kind/kind-config.yaml"

echo "==> Building container images"
docker build -f "${ROOT}/email-gateway/Containerfile" -t helpdesk-email-gateway:ci "${ROOT}"
docker build -f "${ROOT}/agent-dashboard/Containerfile" -t helpdesk-triage-ui:ci "${ROOT}"
docker build -f "${ROOT}/inference-mock/Containerfile" -t helpdesk-inference-mock:ci "${ROOT}/inference-mock"

echo "==> Loading images into kind"
kind load docker-image helpdesk-email-gateway:ci --name "$CLUSTER_NAME"
kind load docker-image helpdesk-triage-ui:ci --name "$CLUSTER_NAME"
kind load docker-image helpdesk-inference-mock:ci --name "$CLUSTER_NAME"

echo "==> Applying manifests"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kustomize build --load-restrictor LoadRestrictionsNone "$OVERLAY" | kubectl apply -f -

echo "==> Waiting for deployments"
kubectl wait deployment/inference-mock deployment/email-gateway deployment/agent-dashboard \
  -n "$NAMESPACE" --for=condition=Available --timeout=300s

GATEWAY_URL="http://127.0.0.1:8080"
echo "==> Port-forwarding email-gateway"
kubectl port-forward -n "$NAMESPACE" svc/email-gateway 8080:8080 >/tmp/helpdesk-kind-pf.log 2>&1 &
PF_PID=$!
sleep 3

stop_pf() {
  kill "$PF_PID" >/dev/null 2>&1 || true
  wait "$PF_PID" 2>/dev/null || true
}
trap 'stop_pf; cleanup' EXIT

echo "==> Checking gateway health"
curl -sf "${GATEWAY_URL}/health" >/dev/null

echo "==> Ingesting sample email"
"${ROOT}/scripts/ingest-sample.sh" "${ROOT}/sample_emails/01-billing-double-charge.eml" >/dev/null

echo "==> Waiting for ticket"
for _ in $(seq 1 30); do
  count="$(curl -sf "${GATEWAY_URL}/tickets" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
  if [[ "${count}" -ge 1 ]]; then
    echo "==> Found ${count} ticket(s)"
    kubectl get pods,svc -n "$NAMESPACE"
    exit 0
  fi
  sleep 2
done

echo "No tickets appeared after ingest" >&2
kubectl get pods -n "$NAMESPACE"
exit 1
