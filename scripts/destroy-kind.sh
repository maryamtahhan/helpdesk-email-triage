#!/usr/bin/env bash
# Delete the local kind cluster used for helpdesk testing.
set -euo pipefail

CLUSTER_NAME="${KIND_CLUSTER_NAME:-helpdesk-ci}"

if ! command -v kind >/dev/null 2>&1; then
  echo "kind not found" >&2
  exit 1
fi

if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  echo "==> Deleting kind cluster ${CLUSTER_NAME}"
  kind delete cluster --name "$CLUSTER_NAME"
  echo "Cluster deleted."
else
  echo "No kind cluster named ${CLUSTER_NAME}; nothing to do."
fi
