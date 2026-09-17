#!/usr/bin/env bash
# Tear down Quadlet services, units, containers, network, ticket volume, and sample dir.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=quadlet-lib.sh
source "${ROOT}/scripts/quadlet-lib.sh"

Wipe_CACHE="${WIPE_RHAII_CACHE:-0}"

if [[ "${QUADLET_RESET_CONFIRM:-}" != "1" ]]; then
  echo "Refuses to reset without QUADLET_RESET_CONFIRM=1" >&2
  echo "Example: QUADLET_RESET_CONFIRM=1 make quadlet-reset" >&2
  exit 1
fi

quadlet_require
quadlet_stop_all
quadlet_disable_boot

rm -f "${QUADLET_SYSTEMD_DIR}"/{agent-dashboard,email-gateway,rhaii-cpu-engine}.container \
  "${QUADLET_SYSTEMD_DIR}/helpdesk.network" \
  "${QUADLET_SYSTEMD_DIR}/gateway-data.volume"
quadlet_user_systemctl daemon-reload

podman rm -f rhaii-triage-ui rhaii-email-gateway rhaii-cpu-engine 2>/dev/null || true
podman volume rm gateway-data 2>/dev/null || podman volume rm gateway-data.volume 2>/dev/null || true
podman network rm helpdesk 2>/dev/null || true

rm -rf "${QUADLET_DATA}/sample_emails" "${QUADLET_DATA}/docs"
mkdir -p "${QUADLET_DATA}/sample_emails" "${QUADLET_DATA}/docs" "${QUADLET_CACHE}"

if [[ "${Wipe_CACHE}" == "1" ]]; then
  rm -rf "${QUADLET_CACHE:?}"/*
  mkdir -p "${QUADLET_CACHE}"
fi

echo "quadlet: reset complete (secrets.env and rhaii-cache kept unless WIPE_RHAII_CACHE=1)."
echo "Run: make quadlet-setup quadlet-build quadlet-up"
