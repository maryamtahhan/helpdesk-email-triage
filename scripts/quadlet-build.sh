#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=quadlet-lib.sh
source "${ROOT}/scripts/quadlet-lib.sh"

quadlet_require
cd "${ROOT}"
podman build -f email-gateway/Containerfile -t localhost/helpdesk-email-triage-email-gateway:prod .
podman build -f agent-dashboard/Containerfile -t localhost/helpdesk-email-triage-ui:prod .
echo "quadlet: images tagged localhost/helpdesk-email-triage-email-gateway:prod and localhost/helpdesk-email-triage-ui:prod"
