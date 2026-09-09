#!/usr/bin/env bash
# Run a GuideLLM benchmark Job against rhaii-cpu in OpenShift (RHAII only — not mock inference).
#
# Red Hat image (registry.redhat.io/rhai/guidellm-rhel9) uses `guidellm run` (GuideLLM 0.7+ CLI).
# Upstream ghcr.io/vllm-project/guidellm uses `guidellm benchmark run` (legacy CLI).
#
# Follows the in-cluster Job pattern from:
# https://developers.redhat.com/articles/2025/12/24/how-deploy-and-benchmark-vllm-guidellm-kubernetes
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=openshift-rhaii-secrets.sh
source "${ROOT}/scripts/openshift-rhaii-secrets.sh"
NAMESPACE="${1:-helpdesk-email-triage}"
GUIDELLM_REDHAT_IMAGE="${GUIDELLM_REDHAT_IMAGE:-registry.redhat.io/rhai/guidellm-rhel9:3.5.0-1787154406}"
IMAGE="${GUIDELLM_IMAGE:-${GUIDELLM_REDHAT_IMAGE}}"
PVC_NAME="${GUIDELLM_PVC:-guidellm-results}"
RESULTS_DIR="${GUIDELLM_RESULTS_DIR:-results/guidellm-openshift}"
WAIT_TIMEOUT="${GUIDELLM_WAIT_TIMEOUT:-1800s}"
PULL_SECRETS_BLOCK=""
# Quickstart defaults (override for a full sweep per the Red Hat article: RATE=1,2,4 MAX_SECONDS=300)
RATE="${GUIDELLM_RATE:-2,4}"
MAX_SECONDS="${GUIDELLM_MAX_SECONDS:-120}"
DATA="${GUIDELLM_DATA:-{\"prompt_tokens\":128,\"output_tokens\":64}}"

guidellm_resolve_cli_mode() {
  if [[ -n "${GUIDELLM_CLI:-}" ]]; then
    echo "$GUIDELLM_CLI"
  elif [[ "$IMAGE" == registry.redhat.io/rhai/* ]]; then
    echo "run"
  else
    echo "benchmark"
  fi
}

if ! command -v oc >/dev/null 2>&1; then
  echo "oc not found" >&2
  exit 1
fi

if ! oc get namespace "$NAMESPACE" >/dev/null 2>&1; then
  echo "Namespace ${NAMESPACE} not found." >&2
  exit 1
fi

if ! oc get deployment rhaii-cpu -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "GuideLLM requires rhaii-cpu (RHAII CPU inference) in ${NAMESPACE}." >&2
  echo "Mock-only overlays are not supported. Deploy with INFERENCE=rhaii or a rhaii-demo / hardened-rhaii overlay." >&2
  exit 1
fi

SERVICE="rhaii-cpu"
MODEL="${GUIDELLM_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"
CLI_MODE="$(guidellm_resolve_cli_mode)"
echo "==> Targeting RHAII CPU (model=${MODEL}, guidellm CLI=${CLI_MODE})"

if [[ "$IMAGE" == registry.redhat.io/* ]]; then
  echo "==> Ensuring registry.redhat.io pull secret (GuideLLM image)"
  if ! ensure_redhat_pull_secret "$NAMESPACE"; then
    echo "GuideLLM on OpenShift requires registry.redhat.io credentials (same as RHAII CPU)." >&2
    echo "  podman login registry.redhat.io" >&2
    echo "  # or set REDHAT_REGISTRY_USERNAME / REDHAT_REGISTRY_PASSWORD" >&2
    exit 1
  fi
  link_pull_secret "$NAMESPACE"
  PULL_SECRETS_BLOCK=$'      imagePullSecrets:\n        - name: redhat-registry-pull'
fi

# Internal cluster DNS — avoids Route/ingress latency (per Red Hat benchmarking guidance).
TARGET="http://${SERVICE}.${NAMESPACE}.svc.cluster.local:8000"
PROCESSOR="${GUIDELLM_PROCESSOR:-$MODEL}"

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

if [[ "$CLI_MODE" == "run" ]]; then
  BENCHMARK_ARGS=$'            - run\n            - --backend\n            - kind=openai_http,target='"${TARGET}"',model='"${MODEL}"$'\n            - --tokenizer\n            - kind=huggingface_auto,model='"${PROCESSOR}"$'\n            - --data\n            - kind=synthetic_text,prompt_tokens='"${PROMPT_TOKENS}"',output_tokens='"${OUTPUT_TOKENS}"$'\n            - --profile\n            - '"'"${PROFILE_JSON}"'"$'\n            - --constraint\n            - kind=max_duration,seconds='"${MAX_SECONDS}"$'\n            - --output\n            - kind=json,path=/results/benchmark-results.json\n            - --output\n            - kind=html,path=/results/benchmark-results.html'
  RUN_HTML_JOB=0
else
  PROCESSOR_ARGS=$'            - --processor\n            - '"${PROCESSOR}"
  REPORT_SOURCE="${GUIDELLM_REPORT_SOURCE:-https://vllm-project.github.io/guidellm/ui/v0.7.1/index.html}"
  BENCHMARK_ARGS=$'            - benchmark\n            - run\n            - --target\n            - '"${TARGET}"$'\n            - --model\n            - '"${MODEL}"$'\n'"${PROCESSOR_ARGS}"$'\n            - --data\n            - '"'"${DATA}"'"$'\n            - --rate-type\n            - concurrent\n            - --rate\n            - '"${RATE}"$'\n            - --max-seconds\n            - '"${MAX_SECONDS}"$'\n            - --output-dir\n            - /results\n            - --outputs\n            - benchmark-results.json'
  RUN_HTML_JOB=1
fi

echo "==> Ensuring GuideLLM can reach inference (NetworkPolicy)"
oc apply -n "$NAMESPACE" -f "${ROOT}/deploy/openshift/components/network-policy/allow-guidellm-to-inference.yaml"

if ! oc get pvc "$PVC_NAME" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "==> Creating PVC ${PVC_NAME} for benchmark artifacts"
  oc apply -n "$NAMESPACE" -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${PVC_NAME}
  labels:
    app.kubernetes.io/part-of: helpdesk-email-triage
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
EOF
fi

HF_ENV_BLOCK=""
if oc get secret hf-secret -n "$NAMESPACE" >/dev/null 2>&1; then
  HF_ENV_BLOCK="            - name: HF_TOKEN
              valueFrom:
                secretKeyRef:
                  name: hf-secret
                  key: HF_TOKEN"
else
  echo "WARNING: hf-secret not found; GuideLLM may fail to load the processor for ${MODEL}" >&2
fi

guidellm_copy_results() {
  local job_name="$1"
  local inspector="guidellm-pvc-inspector-${job_name}"
  mkdir -p "${RESULTS_DIR}"
  oc apply -n "$NAMESPACE" -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${inspector}
  labels:
    app.kubernetes.io/part-of: helpdesk-email-triage
spec:
  restartPolicy: Never
  containers:
    - name: inspector
      image: registry.access.redhat.com/ubi9/ubi-minimal:latest
      command: ["sleep", "infinity"]
      volumeMounts:
        - name: results-storage
          mountPath: /mnt/results
  volumes:
    - name: results-storage
      persistentVolumeClaim:
        claimName: ${PVC_NAME}
EOF
  if ! oc wait --for=condition=Ready "pod/${inspector}" -n "$NAMESPACE" --timeout=120s; then
    oc delete pod "${inspector}" -n "$NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
    return 1
  fi
  # PVC is mounted at /mnt/results; use exec+cat (oc cp needs tar, absent in ubi-minimal).
  if oc exec -n "$NAMESPACE" "${inspector}" -- test -f /mnt/results/benchmark-results.json; then
    oc exec -n "$NAMESPACE" "${inspector}" -- cat /mnt/results/benchmark-results.json \
      > "${RESULTS_DIR}/${job_name}.json"
  fi
  if oc exec -n "$NAMESPACE" "${inspector}" -- test -f /mnt/results/benchmark-results.html; then
    oc exec -n "$NAMESPACE" "${inspector}" -- cat /mnt/results/benchmark-results.html \
      > "${RESULTS_DIR}/${job_name}.html"
  fi
  oc delete pod "${inspector}" -n "$NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}

JOB_NAME="guidellm-benchmark-$(date +%s)"
echo "==> Starting benchmark Job ${JOB_NAME} (image=${IMAGE}, target=${TARGET})"
if [[ "$RUN_HTML_JOB" == "1" ]]; then
  echo "    Legacy CLI: JSON first, HTML in a follow-up Job"
else
  echo "    Red Hat CLI: guidellm run (JSON + self-contained HTML in one Job)"
fi

oc apply -n "$NAMESPACE" -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  labels:
    app.kubernetes.io/name: guidellm-benchmark
    app.kubernetes.io/part-of: helpdesk-email-triage
spec:
  ttlSecondsAfterFinished: 600
  backoffLimit: 1
  activeDeadlineSeconds: 2400
  template:
    metadata:
      labels:
        app.kubernetes.io/name: guidellm-benchmark
        app.kubernetes.io/part-of: helpdesk-email-triage
    spec:
      restartPolicy: Never
${PULL_SECRETS_BLOCK}
      containers:
        - name: guidellm
          image: ${IMAGE}
          imagePullPolicy: IfNotPresent
          env:
            - name: HOME
              value: /results
            - name: HF_HOME
              value: /results/.cache
${HF_ENV_BLOCK}
          command: ["guidellm"]
          args:
${BENCHMARK_ARGS}
          volumeMounts:
            - name: results-volume
              mountPath: /results
      volumes:
        - name: results-volume
          persistentVolumeClaim:
            claimName: ${PVC_NAME}
EOF

echo "==> Waiting for benchmark Job to complete (timeout ${WAIT_TIMEOUT})"
if ! oc wait --for=condition=complete "job/${JOB_NAME}" -n "$NAMESPACE" --timeout="${WAIT_TIMEOUT}"; then
  echo "Benchmark Job did not complete successfully. Logs:" >&2
  oc logs -n "$NAMESPACE" "job/${JOB_NAME}" || true
  guidellm_copy_results "${JOB_NAME}" || true
  exit 1
fi

echo "==> GuideLLM console summary"
oc logs -n "$NAMESPACE" "job/${JOB_NAME}"

if [[ "$RUN_HTML_JOB" == "1" ]]; then
  HTML_JOB="${JOB_NAME}-html"
  echo "==> Generating HTML report (Job ${HTML_JOB}, template=${REPORT_SOURCE})"
  oc apply -n "$NAMESPACE" -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${HTML_JOB}
  labels:
    app.kubernetes.io/name: guidellm-benchmark
    app.kubernetes.io/part-of: helpdesk-email-triage
spec:
  ttlSecondsAfterFinished: 600
  backoffLimit: 0
  activeDeadlineSeconds: 600
  template:
    metadata:
      labels:
        app.kubernetes.io/name: guidellm-benchmark
        app.kubernetes.io/part-of: helpdesk-email-triage
    spec:
      restartPolicy: Never
${PULL_SECRETS_BLOCK}
      containers:
        - name: guidellm
          image: ${IMAGE}
          imagePullPolicy: IfNotPresent
          env:
            - name: HOME
              value: /results
            - name: GUIDELLM__REPORT_GENERATION__SOURCE
              value: "${REPORT_SOURCE}"
          command: ["guidellm"]
          args:
            - benchmark
            - from-file
            - /results/benchmark-results.json
            - --output-formats
            - html
            - --output-dir
            - /results
          volumeMounts:
            - name: results-volume
              mountPath: /results
      volumes:
        - name: results-volume
          persistentVolumeClaim:
            claimName: ${PVC_NAME}
EOF

  if oc wait --for=condition=complete "job/${HTML_JOB}" -n "$NAMESPACE" --timeout=300s; then
    echo "==> HTML report generated on PVC"
  else
    echo "WARNING: HTML report Job failed (JSON results are still valid). Logs:" >&2
    oc logs -n "$NAMESPACE" "job/${HTML_JOB}" 2>/dev/null || true
  fi
fi

echo "==> Copying benchmark-results.json and .html to ${RESULTS_DIR}/"
guidellm_copy_results "${JOB_NAME}"

if [[ -f "${RESULTS_DIR}/${JOB_NAME}.json" ]]; then
  echo "==> JSON: ${RESULTS_DIR}/${JOB_NAME}.json"
fi
if [[ -f "${RESULTS_DIR}/${JOB_NAME}.html" ]]; then
  echo "==> Open ${RESULTS_DIR}/${JOB_NAME}.html in a browser for the interactive GuideLLM report"
else
  echo "==> HTML not copied — use the JSON file from ${RESULTS_DIR}/"
fi
echo "==> Done. Methodology: https://developers.redhat.com/articles/2025/12/24/how-deploy-and-benchmark-vllm-guidellm-kubernetes"
