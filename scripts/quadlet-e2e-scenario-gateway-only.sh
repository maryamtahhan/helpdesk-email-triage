#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=quadlet-lib.sh
source "${ROOT}/scripts/quadlet-lib.sh"
# shellcheck source=quadlet-e2e-lib.sh
source "${ROOT}/scripts/quadlet-e2e-lib.sh"

export E2E_SCENARIO="gateway-only"
quadlet_e2e_init
quadlet_e2e_section "start stack (inference + gateway, no dashboard)"

quadlet_install_units
quadlet_start_deps
quadlet_stop_dashboard

if ! quadlet_e2e_preflight_secrets; then
  quadlet_e2e_fail_scenario_early gateway-only "secrets.env missing or still README placeholder"
  exit 1
fi
if [[ "${QUADLET_ALLOW_PLACEHOLDER_SECRETS:-}" == "1" ]]; then
  export QUADLET_E2E_REQUIRE_MODEL=0
fi

quadlet_sync_repo_assets
quadlet_start_engine || quadlet_e2e_fail_scenario_early gateway-only "rhaii-cpu-engine.service failed to start"
quadlet_wait_inference || quadlet_e2e_fail_scenario_early gateway-only "inference did not become ready"
quadlet_start_gateway || quadlet_e2e_fail_scenario_early gateway-only "email-gateway.service failed to start"
quadlet_wait_gateway_ready || quadlet_e2e_fail_scenario_early gateway-only "gateway /health/ready timeout"

quadlet_e2e_assert_cmd "dashboard not listening" quadlet_e2e_assert_dashboard_down || true
quadlet_e2e_assert_cmd "inference /v1/models" quadlet_e2e_assert_inference_up || true
quadlet_e2e_assert_cmd "gateway /health/ready" quadlet_e2e_assert_gateway_ready || true

quadlet_e2e_section "HTTP ingest (integrator path)"
payload="$(quadlet_e2e_ingest_raw "Quadlet E2E gateway-only" "VPN timeout error TLS-TIMEOUT tech support.")"
quadlet_e2e_assert_cmd "POST /ingest/raw" quadlet_e2e_assert_ingest_uses_model "$payload" || true

list_count="$(curl -sf "${GATEWAY_URL%/}/tickets" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
if [[ "${list_count}" -ge 1 ]]; then
  quadlet_e2e_record PASS "GET /tickets count=${list_count}"
else
  quadlet_e2e_record FAIL "GET /tickets empty"
fi

if [[ "$E2E_FAILED" -eq 0 ]]; then
  quadlet_e2e_write_scenario_report gateway-only pass
  quadlet_e2e_scenario_teardown
  exit 0
fi
quadlet_e2e_write_scenario_report gateway-only fail
quadlet_e2e_scenario_teardown
exit 1
