#!/bin/bash
set -euo pipefail

if [[ $# -gt 0 ]]; then
  exec "$@"
fi

STREAMLIT_ENABLE_XSRF="${STREAMLIT_ENABLE_XSRF:-false}"

# On OpenShift, set the public Route host so Streamlit WebSockets work through the router.
if [[ -f /var/run/secrets/kubernetes.io/serviceaccount/token ]]; then
  STREAMLIT_ENABLE_XSRF="${STREAMLIT_ENABLE_XSRF:-true}"
  if [[ -z "${STREAMLIT_BROWSER_SERVER_ADDRESS:-}" ]]; then
    if host="$(python3 /app/scripts/openshift_route_host.py agent-dashboard 2>/dev/null)"; then
      export STREAMLIT_BROWSER_SERVER_ADDRESS="${host}"
      export STREAMLIT_BROWSER_SERVER_PORT="${STREAMLIT_BROWSER_SERVER_PORT:-443}"
      echo "Discovered Streamlit browser host=${host}"
    fi
  fi
fi

STREAMLIT_ARGS=(
  run app.py
  --server.port=8502
  --server.address=127.0.0.1
  --server.headless=true
  --server.enableCORS=false
  --server.enableXsrfProtection="${STREAMLIT_ENABLE_XSRF}"
)

streamlit "${STREAMLIT_ARGS[@]}" &
STREAMLIT_PID=$!

cleanup() {
  kill "$STREAMLIT_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

python3 - <<'PY'
import time
import urllib.request

for _ in range(80):
    try:
        urllib.request.urlopen("http://127.0.0.1:8502/_stcore/health", timeout=1)
        break
    except OSError:
        time.sleep(0.25)
PY

mkdir -p /tmp/helpdesk-runtime
cp -f /app/nginx.gateway.conf /tmp/helpdesk-runtime/nginx.gateway.conf
for _ in $(seq 1 40); do
  if python3 /app/bootstrap_welcome.py; then
    break
  fi
  sleep 0.5
done

exec nginx -c /app/nginx.conf -g 'daemon off;'
