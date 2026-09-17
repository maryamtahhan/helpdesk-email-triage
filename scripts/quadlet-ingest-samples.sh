#!/usr/bin/env bash
# Copy sample .eml into the host watch dir only after gateway + inference are ready.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=quadlet-lib.sh
source "${ROOT}/scripts/quadlet-lib.sh"

quadlet_require
quadlet_wait_gateway_ready
quadlet_sync_repo_assets
echo "quadlet: sample emails copied to ${QUADLET_DATA}/sample_emails (file watcher will ingest)."
