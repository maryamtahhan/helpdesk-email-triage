#!/usr/bin/env bash
# Unit-test overlay resolution and INFERENCE/OVERLAY consistency (no cluster required).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=openshift-lib.sh
source "${ROOT}/scripts/openshift-lib.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

OVERLAY=deploy/openshift/overlays/hardened
resolve_deploy_overlay rhaii
[[ "$RESOLVED_OVERLAY_APPLIED" == "${ROOT}/deploy/openshift/overlays/hardened-rhaii" ]] \
  || fail "expected hardened-rhaii remap, got ${RESOLVED_OVERLAY_APPLIED}"

assert_rejects_overlay() {
  local mode="$1"
  local overlay="$2"
  if OVERLAY="$overlay" bash -c '
    set +e
    ROOT="'"$ROOT"'"
    # shellcheck source=openshift-lib.sh
    source "'"$ROOT"'/scripts/openshift-lib.sh"
    resolve_deploy_overlay "'"$mode"'"
    exit $?
  ' >/dev/null 2>&1; then
    fail "expected INFERENCE=${mode} to reject overlay ${overlay}"
  fi
}

assert_rejects_overlay mock deploy/openshift/overlays/rhaii-demo
assert_rejects_overlay rhaii deploy/openshift/overlays/helpdesk-email-triage

# shellcheck disable=SC2034  # OVERLAY is read by resolve_deploy_overlay
OVERLAY=deploy/openshift/overlays/external-inference
resolve_deploy_overlay mock
[[ "$RESOLVED_OVERLAY_APPLIED" == *external-inference* ]] \
  || fail "external-inference overlay not preserved"

echo "OpenShift overlay resolution tests passed."
