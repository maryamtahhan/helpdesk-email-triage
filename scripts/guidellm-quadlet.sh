#!/usr/bin/env bash
# Benchmark RHAII on a Quadlet host (same image + CLI as make guidellm-openshift).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=quadlet-lib.sh
source "${ROOT}/scripts/quadlet-lib.sh"

GUIDELLM_REDHAT_IMAGE="${GUIDELLM_REDHAT_IMAGE:-registry.redhat.io/rhai/guidellm-rhel9:3.5.0-1787154406}"
IMAGE="${GUIDELLM_IMAGE:-${GUIDELLM_REDHAT_IMAGE}}"
RESULTS_DIR="${GUIDELLM_RESULTS_DIR:-results/guidellm-quadlet}"
TARGET="${GUIDELLM_TARGET:-http://127.0.0.1:8000}"
MODEL="${GUIDELLM_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"
PROCESSOR="${GUIDELLM_PROCESSOR:-$MODEL}"
RATE="${GUIDELLM_RATE:-2,4}"
MAX_SECONDS="${GUIDELLM_MAX_SECONDS:-120}"
DATA="${GUIDELLM_DATA:-{\"prompt_tokens\":128,\"output_tokens\":64}}"
# host: published :8000 on the EC2/RHEL host; helpdesk: podman network (rhaii-cpu-engine:8000)
PODMAN_NETWORK="${GUIDELLM_PODMAN_NETWORK:-host}"

if [[ "$IMAGE" != registry.redhat.io/rhai/* ]]; then
  echo "guidellm-quadlet: use the Red Hat image (same as OpenShift), e.g. ${GUIDELLM_REDHAT_IMAGE}" >&2
  echo "  Override only for debugging: GUIDELLM_IMAGE=..." >&2
  exit 1
fi

quadlet_require

if [[ -f "${QUADLET_SECRETS}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${QUADLET_SECRETS}"
  set +a
fi
export HF_TOKEN="${HF_TOKEN:-${HUGGING_FACE_HUB_TOKEN:-}}"

if [[ -z "${HF_TOKEN}" ]]; then
  echo "guidellm-quadlet: set HF_TOKEN or HUGGING_FACE_HUB_TOKEN in ${QUADLET_SECRETS}" >&2
  exit 1
fi

if ! curl -sf "${TARGET%/}/v1/models" >/dev/null 2>&1; then
  echo "guidellm-quadlet: waiting for inference at ${TARGET}..." >&2
  INFERENCE_URL="${TARGET}" RHAII_WAIT_TIMEOUT="${GUIDELLM_WAIT_TIMEOUT:-300}" \
    quadlet_wait_inference || exit 1
fi

read -r PROMPT_TOKENS OUTPUT_TOKENS <<< "$(DATA="$DATA" python3 - <<'PY'
import json, os
d = json.loads(os.environ["DATA"])
print(d.get("prompt_tokens", 128), d.get("output_tokens", 64))
PY
)"

PROFILE_JSON="$(RATE="$RATE" python3 - <<'PY'
import json, os
streams = [int(x.strip()) for x in os.environ["RATE"].split(",") if x.strip()]
print(json.dumps({"kind": "concurrent", "streams": streams}))
PY
)"

mkdir -p "${RESULTS_DIR}" "${RESULTS_DIR}/.cache" "${QUADLET_CACHE}"
# GuideLLM runs non-root; ensure mount points are writable (see HF_HOME below).
chmod -R a+rwX "${RESULTS_DIR}" 2>/dev/null || true

RUN_ID="guidellm-$(date +%s)"
OUT_JSON="${RESULTS_DIR}/${RUN_ID}.json"
OUT_HTML="${RESULTS_DIR}/${RUN_ID}.html"

echo "==> GuideLLM Quadlet benchmark"
echo "    image:   ${IMAGE}"
echo "    target:  ${TARGET}"
echo "    model:   ${MODEL}"
echo "    network: ${PODMAN_NETWORK}"
echo "    profile: ${PROFILE_JSON} (max ${MAX_SECONDS}s)"

podman run --rm --network "${PODMAN_NETWORK}" \
  -v "$(cd "${RESULTS_DIR}" && pwd):/results:Z" \
  -v "${QUADLET_CACHE}:/hf-cache:Z" \
  -e HOME=/results \
  -e HF_HOME=/hf-cache \
  -e HF_TOKEN="${HF_TOKEN}" \
  -e HUGGING_FACE_HUB_TOKEN="${HF_TOKEN}" \
  --entrypoint guidellm \
  "${IMAGE}" \
  run \
  --backend "kind=openai_http,target=${TARGET},model=${MODEL}" \
  --tokenizer "kind=huggingface_auto,model=${PROCESSOR}" \
  --data "kind=synthetic_text,prompt_tokens=${PROMPT_TOKENS},output_tokens=${OUTPUT_TOKENS}" \
  --profile "${PROFILE_JSON}" \
  --constraint "kind=max_duration,seconds=${MAX_SECONDS}" \
  --output "kind=json,path=/results/$(basename "${OUT_JSON}")" \
  --output "kind=html,path=/results/$(basename "${OUT_HTML}")"

ln -sf "$(basename "${OUT_JSON}")" "${RESULTS_DIR}/benchmark-results.json"
ln -sf "$(basename "${OUT_HTML}")" "${RESULTS_DIR}/benchmark-results.html"

echo "==> Wrote ${OUT_JSON}"
echo "==> Wrote ${OUT_HTML}"
echo "==> Open ${OUT_HTML} in a browser (symlinks: benchmark-results.html)"
