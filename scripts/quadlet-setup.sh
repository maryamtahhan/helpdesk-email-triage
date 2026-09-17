#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=quadlet-lib.sh
source "${ROOT}/scripts/quadlet-lib.sh"

quadlet_require
quadlet_ensure_dirs
quadlet_ensure_secrets_template
quadlet_sync_repo_assets
quadlet_install_units

echo "quadlet: setup done."
echo "  secrets:  ${QUADLET_SECRETS}"
echo "  samples:  ${QUADLET_DATA}/sample_emails"
echo "Next: podman login registry.redhat.io"
echo "      make quadlet-build && make quadlet-up"
