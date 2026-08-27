#!/usr/bin/env bash
# Run gateway-only compose with TICKET_SINK pointing at a local webhook receiver.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${WEBHOOK_PORT:-9999}"
SECRET="${TICKET_SINK_SECRET:-demo-secret}"
HOOK_PATH="${WEBHOOK_PATH:-/hook}"
HOOK_URL="http://host.containers.internal:${PORT}${HOOK_PATH}"

# Podman on macOS/Linux can reach the host via host.containers.internal.
# Fall back to 127.0.0.1 for native/local gateway runs.
if [[ "${USE_HOST_LOOPBACK:-}" == "1" ]]; then
  HOOK_URL="http://127.0.0.1:${PORT}${HOOK_PATH}"
fi

chmod +x "$ROOT/scripts/webhook-receiver.py"
echo "Starting webhook receiver on 127.0.0.1:${PORT}${HOOK_PATH}"
"$ROOT/scripts/webhook-receiver.py" --port "$PORT" --path "$HOOK_PATH" --secret "$SECRET" &
RECEIVER_PID=$!
cleanup() {
  kill "$RECEIVER_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo
echo "Starting gateway-only stack with:"
echo "  TICKET_SINK=webhook:${HOOK_URL}"
echo "  TICKET_SINK_SECRET=${SECRET}"
echo
echo "In another terminal: ./scripts/ingest-sample.sh"
echo "Press Ctrl-C to stop."
echo

cd "$ROOT"
export TICKET_SINK="webhook:${HOOK_URL}"
export TICKET_SINK_SECRET="$SECRET"
exec podman compose -f compose.gateway-only.yml up --build
