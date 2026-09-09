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
  --server.port=8501
  --server.address=0.0.0.0
  --server.headless=true
  --server.enableCORS=false
  --server.enableXsrfProtection="${STREAMLIT_ENABLE_XSRF}"
)

exec streamlit "${STREAMLIT_ARGS[@]}"
