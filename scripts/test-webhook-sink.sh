#!/usr/bin/env bash
# End-to-end TICKET_SINK demo: local receiver + one triaged ticket (no compose).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${WEBHOOK_PORT:-$((9000 + RANDOM % 1000))}"
SECRET="${TICKET_SINK_SECRET:-demo-secret}"
HOOK_PATH="${WEBHOOK_PATH:-/hook}"
HOOK_URL="http://127.0.0.1:${PORT}${HOOK_PATH}"

if [[ -d "$ROOT/.venv" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
else
  python3 -m venv "$ROOT/.venv"
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  pip install -q -r "$ROOT/email-gateway/requirements.txt"
fi

TMP_DATA="$(mktemp -d)"
cleanup() {
  if [[ -n "${RECEIVER_PID:-}" ]]; then
    kill "$RECEIVER_PID" 2>/dev/null || true
    wait "$RECEIVER_PID" 2>/dev/null || true
  fi
  rm -rf "$TMP_DATA"
}
trap cleanup EXIT

chmod +x "$ROOT/scripts/webhook-receiver.py"
"$ROOT/scripts/webhook-receiver.py" \
  --port "$PORT" \
  --path "$HOOK_PATH" \
  --secret "$SECRET" \
  --once &
RECEIVER_PID=$!
sleep 0.3

export TICKET_DATA_DIR="$TMP_DATA"
export TICKET_SINK="webhook:${HOOK_URL}"
export TICKET_SINK_SECRET="$SECRET"
export TICKET_SINK_SYNC=1
export PYTHONPATH="$ROOT/email-gateway"

python3 - <<'PY'
import importlib
from unittest.mock import patch

import app.store as store_mod

importlib.reload(store_mod)

from app.pipeline import process_parsed_email

fake_result = {
    "category": "Tech Support",
    "urgency": "High",
    # Preserve regex tokens so merge does not warn during the demo run.
    "sanitized_text": "My VPN drops. Please call [NAME_1] at [PHONE_1].",
    "summary": "Customer reports frequent VPN disconnects.",
    "model": "mock-triage",
}

with patch("app.pipeline.inference.classify_and_sanitize", return_value=fake_result):
    ticket = process_parsed_email(
        sender="Sam Okonkwo <sam.okonkwo@example.com>",
        subject="VPN drops every 10 minutes",
        body="My VPN drops. Please call Sam Okonkwo at +1-212-555-0199.",
        source="test-webhook-sink",
    )

print(f"\nIngest complete: {ticket['id']} ({ticket['category']} / {ticket['urgency']})")
PY

wait "$RECEIVER_PID"
echo
echo "Webhook sink test passed."
