#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=quadlet-lib.sh
source "${ROOT}/scripts/quadlet-lib.sh"

quadlet_require

echo "==> systemctl --user"
quadlet_user_systemctl status rhaii-cpu-engine.service email-gateway.service agent-dashboard.service \
  --no-pager -l 2>/dev/null || true

echo
echo "==> health"
curl -sS "${GATEWAY_URL%/}/health" || true
echo
curl -sS "${GATEWAY_URL%/}/health/ready" || true
echo

echo "==> tickets (model field)"
curl -sS "${GATEWAY_URL%/}/tickets" | python3 -c '
import json, sys
tickets = json.load(sys.stdin)
for t in tickets[:8]:
    print(t.get("id"), t.get("model"))
print(f"... total {len(tickets)} tickets")
' 2>/dev/null || echo "(no tickets yet)"

echo
echo "Dashboard: ${DASHBOARD_URL}/welcome"
echo "Inbox:     ${DASHBOARD_URL}/inbox/"
