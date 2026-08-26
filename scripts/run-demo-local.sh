#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

pip install -q -r email-gateway/requirements.txt \
  -r agent-dashboard/requirements.txt \
  -r inference-mock/requirements.txt

export TICKET_DATA_DIR="$ROOT/data"
export EMAIL_INPUT_DIR="$ROOT/sample_emails"
export VLLM_ENDPOINT="http://127.0.0.1:8000/v1/chat/completions"
export VLLM_BASE_URL="http://127.0.0.1:8000/v1"
export MODEL_NAME="mock-triage"
export GATEWAY_MODE="FILE_WATCHER"
export GATEWAY_URL="http://127.0.0.1:8080"
export SMTP_PORT="3025"
mkdir -p "$TICKET_DATA_DIR"

cleanup() {
  if [[ -n "${MOCK_PID:-}" ]]; then kill "$MOCK_PID" 2>/dev/null || true; fi
  if [[ -n "${GW_PID:-}" ]]; then kill "$GW_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT

(cd "$ROOT/inference-mock" && python -m uvicorn server:app --host 127.0.0.1 --port 8000) &
MOCK_PID=$!
(cd "$ROOT/email-gateway" && python -m uvicorn app.main:app --host 127.0.0.1 --port 8080) &
GW_PID=$!

for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:8000/v1/models" >/dev/null \
    && curl -sf "http://127.0.0.1:8080/health" >/dev/null; then
    break
  fi
  sleep 0.25
done

echo "Mock inference:  http://127.0.0.1:8000"
echo "Email gateway:   http://127.0.0.1:8080"
echo "Agent dashboard: http://127.0.0.1:8501"
echo "SMTP ingest:     127.0.0.1:3025"
echo
echo "Sample .eml files in sample_emails/ are ingested automatically."
echo "Opening http://127.0.0.1:8501 in your browser…"

# Open browser (macOS: open, Linux: xdg-open)
if command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:8501"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:8501" &
fi

python -m streamlit run "$ROOT/agent-dashboard/app.py" \
  --server.port 8501 \
  --server.headless true \
  --server.address 127.0.0.1
