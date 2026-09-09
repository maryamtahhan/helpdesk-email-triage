#!/usr/bin/env bash
# Run a GuideLLM benchmark Job against inference-mock or rhaii-cpu in OpenShift.
#
# Follows the in-cluster Job pattern from:
# https://developers.redhat.com/articles/2025/12/24/how-deploy-and-benchmark-vllm-guidellm-kubernetes
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${1:-helpdesk-email-triage}"
IMAGE="${GUIDELLM_IMAGE:-ghcr.io/vllm-project/guidellm:v0.5.0}"
PVC_NAME="${GUIDELLM_PVC:-guidellm-results}"
RESULTS_DIR="${GUIDELLM_RESULTS_DIR:-results/guidellm-openshift}"
# Quickstart defaults (override for a full sweep per the Red Hat article: RATE=1,2,4 MAX_SECONDS=300)
RATE="${GUIDELLM_RATE:-2,4}"
MAX_SECONDS="${GUIDELLM_MAX_SECONDS:-120}"
DATA="${GUIDELLM_DATA:-{\"prompt_tokens\":128,\"output_tokens\":64}}"

if ! command -v oc >/dev/null 2>&1; then
  echo "oc not found" >&2
  exit 1
fi

if ! oc get namespace "$NAMESPACE" >/dev/null 2>&1; then
  echo "Namespace ${NAMESPACE} not found." >&2
  exit 1
fi

if oc get deployment rhaii-cpu -n "$NAMESPACE" >/dev/null 2>&1; then
  SERVICE="rhaii-cpu"
  MODEL="${GUIDELLM_MODEL:-Qwen/Qwen2.5-1.5B-Instruct}"
  USE_HF_SECRET=1
  echo "==> Targeting RHAII CPU (model=${MODEL})"
elif oc get deployment inference-mock -n "$NAMESPACE" >/dev/null 2>&1; then
  SERVICE="inference-mock"
  MODEL="${GUIDELLM_MODEL:-mock-triage}"
  USE_HF_SECRET=0
  echo "==> Targeting mock inference (model=${MODEL})"
else
  echo "No inference-mock or rhaii-cpu deployment in ${NAMESPACE}." >&2
  exit 1
fi

# Internal cluster DNS — avoids Route/ingress latency (per Red Hat benchmarking guidance).
TARGET="http://${SERVICE}.${NAMESPACE}.svc.cluster.local:8000"
PROCESSOR_ARGS=""
if [[ "$USE_HF_SECRET" == "1" ]]; then
  PROCESSOR="${GUIDELLM_PROCESSOR:-$MODEL}"
  PROCESSOR_ARGS=$'- --processor\n            - '"${PROCESSOR}"
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

JOB_NAME="guidellm-benchmark-$(date +%s)"
echo "==> Starting Job ${JOB_NAME} (image=${IMAGE}, target=${TARGET})"

HF_ENV_BLOCK=""
if [[ "$USE_HF_SECRET" == "1" ]] && oc get secret hf-secret -n "$NAMESPACE" >/dev/null 2>&1; then
  HF_ENV_BLOCK="            - name: HF_TOKEN
              valueFrom:
                secretKeyRef:
                  name: hf-secret
                  key: HF_TOKEN"
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
  template:
    metadata:
      labels:
        app.kubernetes.io/name: guidellm-benchmark
        app.kubernetes.io/part-of: helpdesk-email-triage
    spec:
      restartPolicy: Never
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
            - benchmark
            - run
            - --target
            - ${TARGET}
            - --model
            - ${MODEL}
${PROCESSOR_ARGS}
            - --data
            - '${DATA}'
            - --rate-type
            - concurrent
            - --rate
            - "${RATE}"
            - --max-seconds
            - "${MAX_SECONDS}"
            - --output-dir
            - /results
            - --outputs
            - benchmark-results.json,benchmark-results.html
          volumeMounts:
            - name: results-volume
              mountPath: /results
      volumes:
        - name: results-volume
          persistentVolumeClaim:
            claimName: ${PVC_NAME}
EOF

echo "==> Waiting for Job to complete (timeout 15m)"
if ! oc wait --for=condition=complete "job/${JOB_NAME}" -n "$NAMESPACE" --timeout=900s; then
  echo "Job did not complete successfully. Logs:" >&2
  oc logs -n "$NAMESPACE" "job/${JOB_NAME}" || true
  exit 1
fi

echo "==> GuideLLM console summary"
oc logs -n "$NAMESPACE" "job/${JOB_NAME}"

INSPECTOR="guidellm-pvc-inspector-${JOB_NAME}"
echo "==> Copying benchmark-results.json and .html to ${RESULTS_DIR}/"
mkdir -p "${RESULTS_DIR}"
oc apply -n "$NAMESPACE" -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: ${INSPECTOR}
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

if oc wait --for=condition=Ready "pod/${INSPECTOR}" -n "$NAMESPACE" --timeout=120s; then
  oc cp "${NAMESPACE}/${INSPECTOR}:/results/benchmark-results.json" \
    "${RESULTS_DIR}/${JOB_NAME}.json" 2>/dev/null || true
  oc cp "${NAMESPACE}/${INSPECTOR}:/results/benchmark-results.html" \
    "${RESULTS_DIR}/${JOB_NAME}.html" 2>/dev/null || true
fi
oc delete pod "${INSPECTOR}" -n "$NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true

if [[ -f "${RESULTS_DIR}/${JOB_NAME}.html" ]]; then
  echo "==> Open ${RESULTS_DIR}/${JOB_NAME}.html in a browser for the interactive GuideLLM report"
fi
echo "==> Done. Methodology: https://developers.redhat.com/articles/2025/12/24/how-deploy-and-benchmark-vllm-guidellm-kubernetes"
