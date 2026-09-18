#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=quadlet-lib.sh
source "${ROOT}/scripts/quadlet-lib.sh"
# shellcheck source=quadlet-e2e-lib.sh
source "${ROOT}/scripts/quadlet-e2e-lib.sh"

export E2E_SCENARIO="full"
quadlet_e2e_init
quadlet_e2e_section "start stack (inference + gateway + dashboard)"

quadlet_install_units
quadlet_start_deps

if ! quadlet_e2e_preflight_secrets; then
  quadlet_e2e_fail_scenario_early full "secrets.env missing or still README placeholder"
  exit 1
fi
quadlet_sync_repo_assets
if [[ "${QUADLET_ALLOW_PLACEHOLDER_SECRETS:-}" == "1" ]]; then
  export QUADLET_E2E_REQUIRE_MODEL=0
fi

quadlet_start_engine || quadlet_e2e_fail_scenario_early full "rhaii-cpu-engine.service failed to start"
quadlet_wait_inference || quadlet_e2e_fail_scenario_early full "inference did not become ready"
quadlet_start_gateway_stack || quadlet_e2e_fail_scenario_early full "email-gateway or agent-dashboard failed to start"
quadlet_wait_gateway_ready || quadlet_e2e_fail_scenario_early full "gateway /health/ready timeout"

quadlet_e2e_assert_cmd "inference /v1/models" quadlet_e2e_assert_inference_up || true
quadlet_e2e_assert_cmd "gateway /health" quadlet_e2e_assert_gateway_health || true
quadlet_e2e_assert_cmd "gateway /health/ready" quadlet_e2e_assert_gateway_ready || true
quadlet_e2e_assert_cmd "dashboard /welcome" quadlet_e2e_assert_dashboard_up || true

quadlet_e2e_section "HTTP ingest"
payload="$(quadlet_e2e_ingest_raw "Quadlet E2E full HTTP" "Double charge on card ACC-112233. Billing urgent.")"
quadlet_e2e_assert_cmd "POST /ingest/raw returns model" \
  quadlet_e2e_assert_ingest_uses_model "$payload" || true

quadlet_e2e_section "file watcher ingest"
quadlet_e2e_assert_cmd "sample .eml ingested" quadlet_e2e_assert_file_watcher_ingest || true

if [[ "${QUADLET_E2E_SKIP_GUIDELLM:-}" != "1" ]]; then
  quadlet_e2e_section "GuideLLM (short run)"
  if quadlet_e2e_run_guidellm_short full; then
    quadlet_e2e_record PASS "guidellm benchmark-results.json"
  else
    quadlet_e2e_record FAIL "guidellm benchmark"
  fi
else
  quadlet_e2e_record PASS "guidellm skipped (QUADLET_E2E_SKIP_GUIDELLM=1)"
fi

if [[ "$E2E_FAILED" -eq 0 ]]; then
  quadlet_e2e_write_scenario_report full pass
  quadlet_e2e_scenario_teardown
  exit 0
fi
quadlet_e2e_write_scenario_report full fail
quadlet_e2e_scenario_teardown
exit 1
