#!/usr/bin/env bash
# Smoke-test the nginx + welcome + Streamlit /inbox layout (Quay publish / local).
set -euo pipefail

IMAGE="${1:?image required}"
PORT="${SMOKE_PORT:-28501}"
ENGINE="${CONTAINER_ENGINE:-docker}"

cid="$("$ENGINE" run -d --rm -p "${PORT}:8501" -e GATEWAY_URL=http://127.0.0.1:9 "$IMAGE")"
cleanup() { "$ENGINE" rm -f "$cid" >/dev/null 2>&1 || true; }
trap cleanup EXIT

for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${PORT}/_stcore/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

curl -sf "http://127.0.0.1:${PORT}/_stcore/health" >/dev/null
WELCOME_PROBE_URL="http://127.0.0.1:${PORT}/welcome" python3 agent-dashboard/probe-welcome.py
loc="$(curl -sI "http://127.0.0.1:${PORT}/" | awk 'toupper($1)=="LOCATION:"{print $2}' | tr -d '\r')"
[[ "$loc" == *"/welcome"* ]] || { echo "expected / -> /welcome redirect, got: ${loc:-none}" >&2; exit 1; }
echo "UI smoke OK (${IMAGE})"
