#!/usr/bin/env bash
# Shared helpers for rootless Podman Quadlet deploy on RHEL.
set -euo pipefail

quadlet_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

QUADLET_SRC="${QUADLET_SRC:-$(quadlet_root)/deploy/quadlet}"
QUADLET_SYSTEMD_DIR="${QUADLET_SYSTEMD_DIR:-${HOME}/.config/containers/systemd}"
QUADLET_SECRETS="${QUADLET_SECRETS:-${HOME}/.config/helpdesk/secrets.env}"
QUADLET_DATA="${QUADLET_DATA:-${HOME}/helpdesk}"
QUADLET_CACHE="${QUADLET_CACHE:-${HOME}/rhaii-cache}"

INFERENCE_URL="${INFERENCE_URL:-http://127.0.0.1:8000}"
GATEWAY_URL="${GATEWAY_URL:-http://127.0.0.1:8080}"
DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:8501}"

RHAII_WAIT_INTERVAL="${RHAII_WAIT_INTERVAL:-15}"
RHAII_WAIT_TIMEOUT="${RHAII_WAIT_TIMEOUT:-900}"

quadlet_require() {
  local missing=0
  for cmd in systemctl podman curl python3; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      echo "quadlet: required command not found: $cmd" >&2
      missing=1
    fi
  done
  if [[ "$missing" -ne 0 ]]; then
    exit 1
  fi
}

quadlet_user_systemctl() {
  systemctl --user "$@"
}

quadlet_install_units() {
  mkdir -p "${QUADLET_SYSTEMD_DIR}"
  cp "${QUADLET_SRC}"/*.container "${QUADLET_SRC}"/*.network "${QUADLET_SRC}"/*.volume \
    "${QUADLET_SYSTEMD_DIR}/"
  quadlet_user_systemctl daemon-reload
}

quadlet_ensure_dirs() {
  mkdir -p "${QUADLET_SYSTEMD_DIR}" "${HOME}/.config/helpdesk" \
    "${QUADLET_DATA}/sample_emails" "${QUADLET_DATA}/docs" "${QUADLET_CACHE}"
}

quadlet_ensure_secrets_template() {
  if [[ -f "${QUADLET_SECRETS}" ]]; then
    return 0
  fi
  cat >"${QUADLET_SECRETS}" <<'EOF'
HUGGING_FACE_HUB_TOKEN=hf_your_token_here
VAULT_SECRET=change-me-before-deploy
EOF
  chmod 600 "${QUADLET_SECRETS}"
  echo "quadlet: created template ${QUADLET_SECRETS} — set a real HUGGING_FACE_HUB_TOKEN before RHAII start."
}

quadlet_secrets_ok() {
  if [[ ! -f "${QUADLET_SECRETS}" ]]; then
    echo "quadlet: missing ${QUADLET_SECRETS}" >&2
    return 1
  fi
  if grep -q 'hf_your_token_here' "${QUADLET_SECRETS}" 2>/dev/null; then
    echo "quadlet: replace placeholder HUGGING_FACE_HUB_TOKEN in ${QUADLET_SECRETS}" >&2
    return 1
  fi
  return 0
}

quadlet_sync_repo_assets() {
  local root
  root="$(quadlet_root)"
  cp -r "${root}/sample_emails/." "${QUADLET_DATA}/sample_emails/"
  cp -r "${root}/docs/." "${QUADLET_DATA}/docs/"
}

quadlet_start_deps() {
  local unit
  for unit in helpdesk-network.service helpdesk.service; do
    if quadlet_user_systemctl cat "${unit}" &>/dev/null; then
      quadlet_user_systemctl start "${unit}"
      break
    fi
  done
  if quadlet_user_systemctl cat gateway-data-volume.service &>/dev/null; then
    quadlet_user_systemctl start gateway-data-volume.service
  elif quadlet_user_systemctl cat gateway-data.service &>/dev/null; then
    quadlet_user_systemctl start gateway-data.service
  fi
  quadlet_ensure_podman_network
  quadlet_ensure_data_volume
}

quadlet_ensure_podman_network() {
  if podman network inspect helpdesk &>/dev/null; then
    return 0
  fi
  echo "quadlet: podman network helpdesk missing after network unit start; creating..." >&2
  podman network create helpdesk
}

quadlet_ensure_data_volume() {
  if podman volume inspect gateway-data &>/dev/null; then
    return 0
  fi
  podman volume create gateway-data
}

quadlet_diagnose_engine_start() {
  echo "quadlet: --- diagnose (podman exit 125 = run failed immediately) ---" >&2
  quadlet_user_systemctl list-unit-files '*helpdesk*' '*gateway*' '*rhaii*' 2>/dev/null || true
  echo "quadlet: networks:" >&2
  podman network ls 2>/dev/null || true
  podman network inspect helpdesk 2>&1 || true
  echo "quadlet: port 8000:" >&2
  ss -tlnp 2>/dev/null | grep ':8000 ' || true
  echo "quadlet: cache dir ${QUADLET_CACHE}:" >&2
  ls -ld "${QUADLET_CACHE}" 2>&1 || true
  if [[ -f "${QUADLET_SECRETS}" ]]; then
    echo "quadlet: secrets.env (names only):" >&2
    grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "${QUADLET_SECRETS}" | cut -d= -f1 >&2 || true
  fi
  echo "quadlet: try: podman logs rhaii-cpu-engine --tail 40" >&2
  echo "quadlet: or re-run engine start with stderr:" >&2
  echo "  systemctl --user stop rhaii-cpu-engine.service" >&2
  echo "  podman run --rm --network helpdesk --shm-size 4g \\" >&2
  echo "    -v ${QUADLET_CACHE}:/opt/app-root/src/.cache:Z \\" >&2
  echo "    --env-file ${QUADLET_SECRETS} \\" >&2
  echo "    registry.redhat.io/rhaii/vllm-cpu-rhel9:3.5.0-1786546771 \\" >&2
  echo "    --model Qwen/Qwen2.5-1.5B-Instruct --host 0.0.0.0 --port 8000" >&2
}

quadlet_wait_inference() {
  local url="${INFERENCE_URL%/}/v1/models"
  local deadline=$((SECONDS + RHAII_WAIT_TIMEOUT))
  echo "quadlet: waiting for inference at ${url} (timeout ${RHAII_WAIT_TIMEOUT}s)..."
  while (( SECONDS < deadline )); do
    if curl -sf "${url}" >/dev/null 2>&1; then
      echo "quadlet: inference is up."
      return 0
    fi
    sleep "${RHAII_WAIT_INTERVAL}"
  done
  echo "quadlet: timed out waiting for inference" >&2
  echo "quadlet: try: podman logs rhaii-cpu-engine --tail 80" >&2
  return 1
}

quadlet_wait_gateway_ready() {
  local url="${GATEWAY_URL%/}/health/ready"
  local deadline=$((SECONDS + 120))
  echo "quadlet: waiting for gateway ready at ${url}..."
  while (( SECONDS < deadline )); do
    if curl -sf "${url}" >/dev/null 2>&1; then
      echo "quadlet: gateway is ready."
      return 0
    fi
    sleep 2
  done
  echo "quadlet: gateway /health/ready did not return 200 in time" >&2
  return 1
}

quadlet_start_engine() {
  quadlet_user_systemctl stop rhaii-cpu-engine.service 2>/dev/null || true
  quadlet_user_systemctl reset-failed rhaii-cpu-engine.service 2>/dev/null || true
  podman rm -f rhaii-cpu-engine 2>/dev/null || true
  mkdir -p "${QUADLET_CACHE}"
  if ! quadlet_user_systemctl start rhaii-cpu-engine.service; then
    echo "quadlet: rhaii-cpu-engine.service failed to start" >&2
    quadlet_user_systemctl status rhaii-cpu-engine.service --no-pager -l || true
    journalctl --user -u rhaii-cpu-engine.service -n 40 --no-pager 2>/dev/null || true
    quadlet_diagnose_engine_start
    return 1
  fi
}

quadlet_start_gateway() {
  quadlet_user_systemctl start email-gateway.service
}

quadlet_start_dashboard() {
  quadlet_user_systemctl start agent-dashboard.service
}

quadlet_start_gateway_stack() {
  quadlet_start_gateway
  quadlet_start_dashboard
}

quadlet_stop_dashboard() {
  quadlet_user_systemctl stop agent-dashboard.service 2>/dev/null || true
}

quadlet_clear_ticket_store() {
  if ! podman volume inspect gateway-data &>/dev/null; then
    return 0
  fi
  local mount
  mount="$(podman volume inspect gateway-data --format '{{.Mountpoint}}' 2>/dev/null || true)"
  if [[ -n "$mount" && -d "$mount" ]]; then
    rm -f "${mount}/tickets.json"
  fi
}

quadlet_stop_all() {
  quadlet_user_systemctl stop agent-dashboard.service email-gateway.service rhaii-cpu-engine.service \
    2>/dev/null || true
}

quadlet_disable_boot() {
  quadlet_user_systemctl disable agent-dashboard.service email-gateway.service rhaii-cpu-engine.service \
    2>/dev/null || true
  quadlet_user_systemctl del-wants default.target agent-dashboard.service email-gateway.service \
    rhaii-cpu-engine.service 2>/dev/null || true
}

quadlet_enable_boot() {
  if command -v loginctl >/dev/null 2>&1; then
    sudo loginctl enable-linger "${USER}" 2>/dev/null || \
      echo "quadlet: run: sudo loginctl enable-linger ${USER}"
  fi
  quadlet_user_systemctl add-wants default.target rhaii-cpu-engine.service email-gateway.service \
    agent-dashboard.service 2>/dev/null || true
}
