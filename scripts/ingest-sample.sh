#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
FILE="${1:-$ROOT/sample_emails/01-billing-double-charge.eml}"

curl -sS -X POST "$GATEWAY_URL/ingest" \
  -F "file=@${FILE};type=message/rfc822" | python3 -m json.tool
