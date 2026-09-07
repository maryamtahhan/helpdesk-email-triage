#!/usr/bin/env bash
# Create (or reuse) a kind cluster and deploy the mock stack.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=kind-lib.sh
source "${ROOT}/scripts/kind-lib.sh"

kind_ensure_tools
kind_ensure_cluster
kind_build_and_load_images
kind_apply_stack

kubectl get pods,svc -n "$NAMESPACE"
kind_print_access
