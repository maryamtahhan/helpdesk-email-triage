#!/bin/bash
set -euo pipefail

if [[ $# -gt 0 ]]; then
  exec "$@"
fi

# On OpenShift, discover the dashboard Route hostname for browser CORS automatically.
if [[ -f /var/run/secrets/kubernetes.io/serviceaccount/token ]]; then
  if [[ -z "${DASHBOARD_ORIGIN:-}" || "${DASHBOARD_ORIGIN}" == "http://localhost:8501" ]]; then
    if host="$(python3 /app/scripts/openshift_route_host.py agent-dashboard 2>/dev/null)"; then
      export DASHBOARD_ORIGIN="https://${host}"
      echo "Discovered DASHBOARD_ORIGIN=${DASHBOARD_ORIGIN}"
    fi
  fi
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8080
