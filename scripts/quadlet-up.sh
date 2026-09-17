#!/usr/bin/env bash
# Start Quadlet stack in safe order: network/volume → inference → wait → gateway + UI.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=quadlet-lib.sh
source "${ROOT}/scripts/quadlet-lib.sh"

SKIP_INGEST="${SKIP_INGEST:-0}"
ENABLE_LINGER="${ENABLE_LINGER:-0}"

quadlet_require
quadlet_install_units
quadlet_start_deps

if ! quadlet_secrets_ok; then
  if [[ "${QUADLET_ALLOW_PLACEHOLDER_SECRETS:-}" == "1" ]]; then
    echo "quadlet: warning: placeholder HUGGING_FACE_HUB_TOKEN (cached weights may still work)." >&2
  else
    echo "quadlet: edit ${QUADLET_SECRETS} (real HUGGING_FACE_HUB_TOKEN), or set QUADLET_ALLOW_PLACEHOLDER_SECRETS=1 to override." >&2
    exit 1
  fi
fi

quadlet_start_engine
quadlet_wait_inference
quadlet_start_gateway_stack
quadlet_wait_gateway_ready

if [[ "${ENABLE_LINGER}" == "1" ]]; then
  quadlet_enable_boot
fi

if [[ "${SKIP_INGEST}" != "1" ]]; then
  "${ROOT}/scripts/quadlet-ingest-samples.sh"
fi

"${ROOT}/scripts/quadlet-verify.sh"
