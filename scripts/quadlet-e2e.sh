#!/usr/bin/env bash
# Maintainer validation for RHEL Quadlet deploy paths (requires rootless podman + user systemd).
#
# Scenarios (default: full,gateway-only):
#   full          — inference + gateway + Streamlit, HTTP + file ingest, short GuideLLM, teardown
#   gateway-only  — inference + gateway only (no UI on :8501)
#
# Usage:
#   ./scripts/quadlet-e2e.sh
#   QUADLET_E2E_SCENARIOS=full make quadlet-e2e
#   QUADLET_E2E_SKIP_GUIDELLM=1 make quadlet-e2e
#   QUADLET_E2E_BUILD=1 make quadlet-e2e
#   QUADLET_E2E_INITIAL_RESET=1 make quadlet-e2e   # QUADLET_RESET_CONFIRM=1 reset first
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=quadlet-lib.sh
source "${ROOT}/scripts/quadlet-lib.sh"

SCENARIOS="${QUADLET_E2E_SCENARIOS:-full,gateway-only}"
FAILED=0
export QUADLET_E2E_RUN_ID="${QUADLET_E2E_RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
E2E_REPORT="${ROOT}/results/quadlet-e2e/report-${QUADLET_E2E_RUN_ID}.json"

quadlet_require

if ! systemctl --user show-environment &>/dev/null; then
  echo "quadlet-e2e: user systemd session not available (SSH without linger?)" >&2
  exit 1
fi

if [[ "${QUADLET_E2E_BUILD:-}" == "1" ]]; then
  echo "==> Building prod images"
  "${ROOT}/scripts/quadlet-build.sh"
fi

# shellcheck source=quadlet-e2e-lib.sh
source "${ROOT}/scripts/quadlet-e2e-lib.sh"
if ! quadlet_e2e_preflight_images; then
  exit 1
fi

if [[ "${QUADLET_E2E_INITIAL_RESET:-}" == "1" ]]; then
  echo "==> Initial reset"
  QUADLET_RESET_CONFIRM=1 "${ROOT}/scripts/quadlet-reset.sh"
  "${ROOT}/scripts/quadlet-setup.sh"
fi

echo "==> Quadlet E2E run ${SCENARIOS}"
echo "    results: ${QUADLET_E2E_RESULTS:-results/quadlet-e2e}"
echo "    skip guidellm: ${QUADLET_E2E_SKIP_GUIDELLM:-0}"

if ! quadlet_e2e_preflight_secrets; then
  for raw in $(echo "${SCENARIOS}" | tr ',' ' '); do
    scenario="$(echo "$raw" | xargs)"
    [[ -z "$scenario" ]] && continue
    quadlet_e2e_fail_scenario_early "$scenario" "preflight: fix secrets.env before running E2E"
  done
  exit 1
fi

IFS=',' read -r -a scenario_list <<< "${SCENARIOS}"
for raw in "${scenario_list[@]}"; do
  scenario="$(echo "$raw" | xargs)"
  [[ -z "$scenario" ]] && continue
  script="${ROOT}/scripts/quadlet-e2e-scenario-${scenario}.sh"
  if [[ ! -x "$script" ]] && [[ ! -f "$script" ]]; then
    echo "quadlet-e2e: unknown scenario ${scenario} (no ${script})" >&2
    FAILED=1
    continue
  fi
  chmod +x "$script"
  echo ""
  echo "################################################################"
  echo "# Scenario: ${scenario}"
  echo "################################################################"
  if ! "$script"; then
    FAILED=1
  fi
done

report="${E2E_REPORT}"
summary_rc=0
if [[ -f "$report" ]]; then
  echo ""
  echo "==> Summary (${report})"
  python3 - "$report" <<'PY' || summary_rc=$?
import json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
for s in doc.get("scenarios", []):
    print(f"  {s['scenario']}: {s['status']} ({len(s.get('steps', []))} steps)")
failed = [s for s in doc.get("scenarios", []) if s.get("status") != "pass"]
sys.exit(1 if failed else 0)
PY
else
  echo "quadlet-e2e: no report file written" >&2
  summary_rc=1
fi

if [[ "$FAILED" -ne 0 ]]; then
  exit 1
fi
exit "$summary_rc"
