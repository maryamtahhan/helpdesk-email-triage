#!/usr/bin/env bash
# Poll GET /tickets until at least one ticket exists (or timeout).
set -euo pipefail

GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
ATTEMPTS="${1:-30}"
SLEEP_SEC="${2:-2}"

curl_flags=(-sf)
if [[ "$GATEWAY_URL" == https:* ]]; then
  curl_flags=(-skf)
fi

for _ in $(seq 1 "$ATTEMPTS"); do
  count="$(curl "${curl_flags[@]}" "${GATEWAY_URL}/tickets" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')"
  if [[ "${count}" -ge 1 ]]; then
    echo "${count}"
    exit 0
  fi
  sleep "$SLEEP_SEC"
done

exit 1
