#!/usr/bin/env bash
# Shared helpers for kind deploy scripts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLUSTER_NAME="${KIND_CLUSTER_NAME:-helpdesk-ci}"
NAMESPACE="${KIND_NAMESPACE:-helpdesk-kind-test}"
OVERLAY="${OVERLAY:-${ROOT}/deploy/kind/overlays/mock-demo}"
RECREATE_CLUSTER="${RECREATE_CLUSTER:-0}"

kind_need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "$1 not found" >&2
    exit 1
  }
}

kind_ensure_tools() {
  kind_need docker
  kind_need kind
  kind_need kubectl
  kind_need kustomize
}

kind_cluster_exists() {
  kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"
}

kind_ensure_cluster() {
  if kind_cluster_exists; then
    if [[ "$RECREATE_CLUSTER" == "1" ]]; then
      echo "==> Recreating kind cluster ${CLUSTER_NAME}"
      kind delete cluster --name "$CLUSTER_NAME"
    else
      echo "==> Using existing kind cluster ${CLUSTER_NAME}"
      return 0
    fi
  else
    echo "==> Creating kind cluster ${CLUSTER_NAME}"
  fi
  kind create cluster --name "$CLUSTER_NAME" --config "${ROOT}/deploy/kind/kind-config.yaml"
}

kind_build_and_load_images() {
  echo "==> Building container images"
  docker build -f "${ROOT}/email-gateway/Containerfile" -t helpdesk-email-gateway:ci "${ROOT}"
  docker build -f "${ROOT}/agent-dashboard/Containerfile" -t helpdesk-triage-ui:ci "${ROOT}"
  docker build -f "${ROOT}/inference-mock/Containerfile" -t helpdesk-inference-mock:ci "${ROOT}/inference-mock"

  echo "==> Loading images into kind"
  kind load docker-image helpdesk-email-gateway:ci --name "$CLUSTER_NAME"
  kind load docker-image helpdesk-triage-ui:ci --name "$CLUSTER_NAME"
  kind load docker-image helpdesk-inference-mock:ci --name "$CLUSTER_NAME"
}

kind_apply_stack() {
  echo "==> Applying manifests to namespace ${NAMESPACE}"
  kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
  kustomize build --load-restrictor LoadRestrictionsNone "$OVERLAY" | kubectl apply -f -

  echo "==> Waiting for deployments"
  kubectl wait deployment/inference-mock deployment/email-gateway deployment/agent-dashboard \
    -n "$NAMESPACE" --for=condition=Available --timeout=300s
}

kind_print_access() {
  cat <<EOF

Cluster:   ${CLUSTER_NAME}
Namespace: ${NAMESPACE}

Pods and services:
  kubectl get pods,svc -n ${NAMESPACE}

Port-forward gateway (HTTP + SMTP):
  kubectl port-forward -n ${NAMESPACE} svc/email-gateway 8080:8080 3025:3025

Port-forward dashboard:
  kubectl port-forward -n ${NAMESPACE} svc/agent-dashboard 8501:8501

## Verify
curl -sS http://127.0.0.1:8080/health
./scripts/ingest-sample.sh
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool | head -20
curl -sI http://127.0.0.1:8501 | head -5

Open: http://127.0.0.1:8501

Teardown:
  make destroy-kind
EOF
}
