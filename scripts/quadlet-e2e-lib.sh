#!/usr/bin/env bash
# Assertions and reporting for maintainer Quadlet E2E runs (not end-user docs).
set -euo pipefail

QUADLET_E2E_RESULTS="${QUADLET_E2E_RESULTS:-results/quadlet-e2e}"
QUADLET_E2E_REQUIRE_MODEL="${QUADLET_E2E_REQUIRE_MODEL:-1}"
QUADLET_E2E_EXPECTED_MODEL="${QUADLET_E2E_EXPECTED_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"

export E2E_SCENARIO=""
E2E_STEP_LOG=()
export E2E_FAILED=0
E2E_RUN_ID="$(date +%Y%m%d-%H%M%S)"

quadlet_e2e_init() {
  mkdir -p "${QUADLET_E2E_RESULTS}"
  E2E_STEP_LOG=()
  E2E_FAILED=0
}

quadlet_e2e_preflight_secrets() {
  if quadlet_secrets_ok; then
    return 0
  fi
  if [[ "${QUADLET_ALLOW_PLACEHOLDER_SECRETS:-}" == "1" ]]; then
    echo "quadlet-e2e: warning: placeholder token — model/heuristic checks relaxed." >&2
    return 0
  fi
  cat >&2 <<EOF
quadlet-e2e: invalid ${QUADLET_SECRETS}

The README template value hf_your_token_here is not a real Hugging Face token.
Edit secrets (do not paste tokens into chat):

  vi ${QUADLET_SECRETS}
  # HUGGING_FACE_HUB_TOKEN=hf_<your token from huggingface.co/settings/tokens>
  # Accept the Qwen model license on huggingface.co if required.

Smoke only with cached weights (not a full validation):
  QUADLET_ALLOW_PLACEHOLDER_SECRETS=1 make quadlet-e2e
EOF
  return 1
}

quadlet_e2e_fail_scenario_early() {
  local scenario="$1"
  local reason="$2"
  export E2E_SCENARIO="$scenario"
  quadlet_e2e_init
  quadlet_e2e_record FAIL "$reason"
  quadlet_e2e_write_scenario_report "$scenario" fail
}

quadlet_e2e_section() {
  echo ""
  echo "========== [$E2E_SCENARIO] $* =========="
}

quadlet_e2e_record() {
  local status="$1"
  local msg="$2"
  E2E_STEP_LOG+=("${status}|${msg}")
  if [[ "$status" == "FAIL" ]]; then
    E2E_FAILED=1
    echo "FAIL: ${msg}" >&2
  else
    echo "PASS: ${msg}"
  fi
}

quadlet_e2e_assert_cmd() {
  local name="$1"
  shift
  if "$@"; then
    quadlet_e2e_record PASS "$name"
  else
    quadlet_e2e_record FAIL "$name"
    return 1
  fi
}

quadlet_e2e_assert_inference_up() {
  curl -sf "${INFERENCE_URL%/}/v1/models" >/dev/null
}

quadlet_e2e_assert_gateway_health() {
  curl -sf "${GATEWAY_URL%/}/health" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("status")=="ok" else 1)'
}

quadlet_e2e_assert_gateway_ready() {
  curl -sf "${GATEWAY_URL%/}/health/ready" >/dev/null
}

quadlet_e2e_assert_dashboard_up() {
  local code
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "${DASHBOARD_URL%/}/welcome" || true)"
  [[ "$code" == "200" || "$code" == "302" ]]
}

quadlet_e2e_assert_dashboard_down() {
  ! curl -sf --max-time 2 "${DASHBOARD_URL%/}/welcome" >/dev/null 2>&1
}

quadlet_e2e_ingest_raw() {
  local subject="${1:-Quadlet E2E ingest}"
  local body="${2:-Charged twice on card ACC-998877. Need billing help urgently.}"
  curl -sf -X POST "${GATEWAY_URL%/}/ingest/raw" \
    -H "Content-Type: application/json" \
    -d "$(SUBJECT="$subject" BODY="$body" python3 - <<'PY'
import json, os
print(json.dumps({
    "sender": "e2e@example.com",
    "subject": os.environ["SUBJECT"],
    "body": os.environ["BODY"],
}))
PY
)"
}

quadlet_e2e_assert_ingest_uses_model() {
  local payload="$1"
  REQUIRE_MODEL="${QUADLET_E2E_REQUIRE_MODEL}" \
  EXPECTED="${QUADLET_E2E_EXPECTED_MODEL}" \
  PAYLOAD="$payload" python3 - <<'PY'
import json, os, sys
ticket = json.loads(os.environ["PAYLOAD"])
model = ticket.get("model", "")
require = os.environ.get("REQUIRE_MODEL", "1") == "1"
expected = os.environ.get("EXPECTED", "")
if require:
    if model == "heuristic-fallback":
        print("model is heuristic-fallback (inference likely not ready)", file=sys.stderr)
        sys.exit(1)
    if expected and expected not in model:
        print(f"model {model!r} does not contain {expected!r}", file=sys.stderr)
        sys.exit(1)
if not ticket.get("id"):
    print("missing ticket id", file=sys.stderr)
    sys.exit(1)
if not ticket.get("category"):
    print("missing category", file=sys.stderr)
    sys.exit(1)
print(model, ticket.get("category"))
PY
}

quadlet_e2e_assert_file_watcher_ingest() {
  local root
  root="$(quadlet_root)"
  quadlet_sync_repo_assets
  local before after
  before="$(curl -sf "${GATEWAY_URL%/}/tickets" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
  touch "${QUADLET_DATA}/sample_emails/"*.eml
  if ! count="$("${root}/scripts/wait-for-tickets.sh" 45 2)"; then
    echo "file watcher: no new tickets within timeout (had ${before})" >&2
    return 1
  fi
  after="$count"
  [[ "${after}" -gt "${before}" ]]
}

quadlet_e2e_run_guidellm_short() {
  local subdir="${1:-${E2E_SCENARIO}}"
  local root
  root="$(quadlet_root)"
  GUIDELLM_RESULTS_DIR="${QUADLET_E2E_RESULTS}/${subdir}/guidellm" \
  GUIDELLM_MAX_SECONDS="${QUADLET_E2E_GUIDELLM_SECONDS:-90}" \
  GUIDELLM_RATE="${QUADLET_E2E_GUIDELLM_RATE:-1}" \
  "${root}/scripts/guidellm-quadlet.sh"
  test -s "${QUADLET_E2E_RESULTS}/${subdir}/guidellm/benchmark-results.json"
}

quadlet_e2e_write_scenario_report() {
  local scenario="$1"
  local status="$2"
  local report="${QUADLET_E2E_RESULTS}/report-${E2E_RUN_ID}.json"
  python3 - "$report" "$scenario" "$status" "${E2E_STEP_LOG[@]}" <<'PY'
import json, sys, time
path, scenario, status = sys.argv[1], sys.argv[2], sys.argv[3]
steps = []
for entry in sys.argv[4:]:
    st, msg = entry.split("|", 1)
    steps.append({"status": st, "message": msg})
block = {
    "scenario": scenario,
    "status": status,
    "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "steps": steps,
}
try:
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
except (FileNotFoundError, json.JSONDecodeError):
    doc = {"run_id": path.split("report-")[1].replace(".json", ""), "scenarios": []}
doc["scenarios"].append(block)
with open(path, "w", encoding="utf-8") as fh:
    json.dump(doc, fh, indent=2)
print(path)
PY
}

quadlet_e2e_scenario_teardown() {
  quadlet_stop_all
  quadlet_clear_ticket_store
}
