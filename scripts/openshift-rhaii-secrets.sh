#!/usr/bin/env bash
# Ensure OpenShift secrets required for in-cluster RHAII CPU inference.
set -euo pipefail

namespace="${1:?namespace required}"

registry_auth_file() {
  if [[ -n "${DOCKER_CONFIG:-}" && -f "${DOCKER_CONFIG}/config.json" ]]; then
    echo "${DOCKER_CONFIG}/config.json"
    return 0
  fi
  if [[ -f "${HOME}/.docker/config.json" ]]; then
    echo "${HOME}/.docker/config.json"
    return 0
  fi
  if [[ -n "${XDG_RUNTIME_DIR:-}" && -f "${XDG_RUNTIME_DIR}/containers/auth.json" ]]; then
    echo "${XDG_RUNTIME_DIR}/containers/auth.json"
    return 0
  fi
  return 1
}

ensure_hf_secret() {
  if [[ -n "${HF_TOKEN:-}" ]]; then
    oc create secret generic hf-secret \
      --from-literal=HF_TOKEN="$HF_TOKEN" \
      -n "$namespace" \
      --dry-run=client -o yaml | oc apply -f -
    return 0
  fi
  oc get secret hf-secret -n "$namespace" >/dev/null 2>&1
}

has_hf_secret() {
  [[ -n "${HF_TOKEN:-}" ]] || oc get secret hf-secret -n "$namespace" >/dev/null 2>&1
}

ensure_redhat_pull_secret() {
  if oc get secret redhat-registry-pull -n "$namespace" >/dev/null 2>&1; then
    return 0
  fi

  if [[ -n "${REDHAT_REGISTRY_USERNAME:-}" && -n "${REDHAT_REGISTRY_PASSWORD:-}" ]]; then
    oc create secret docker-registry redhat-registry-pull \
      --docker-server=registry.redhat.io \
      --docker-username="$REDHAT_REGISTRY_USERNAME" \
      --docker-password="$REDHAT_REGISTRY_PASSWORD" \
      -n "$namespace" \
      --dry-run=client -o yaml | oc apply -f -
    return 0
  fi

  local auth_file=""
  auth_file="$(registry_auth_file)" || true
  if [[ -n "$auth_file" ]]; then
    if [[ "$auth_file" == *"auth.json" ]] && command -v jq >/dev/null 2>&1; then
      local auth_b64 user pass
      auth_b64="$(jq -r '.auths["registry.redhat.io"].auth // empty' "$auth_file")"
      if [[ -n "$auth_b64" ]]; then
        userpass="$(printf '%s' "$auth_b64" | base64 -d 2>/dev/null || true)"
        user="${userpass%%:*}"
        pass="${userpass#*:}"
        if [[ -n "$user" && -n "$pass" ]]; then
          oc create secret docker-registry redhat-registry-pull \
            --docker-server=registry.redhat.io \
            --docker-username="$user" \
            --docker-password="$pass" \
            -n "$namespace" \
            --dry-run=client -o yaml | oc apply -f -
          return 0
        fi
      fi
    fi
    if [[ "$auth_file" == *"config.json" ]]; then
      oc create secret generic redhat-registry-pull \
        --from-file=.dockerconfigjson="$auth_file" \
        --type=kubernetes.io/dockerconfigjson \
        -n "$namespace" \
        --dry-run=client -o yaml | oc apply -f -
      return 0
    fi
  fi

  return 1
}

has_redhat_pull_secret() {
  oc get secret redhat-registry-pull -n "$namespace" >/dev/null 2>&1 \
    || [[ -n "${REDHAT_REGISTRY_USERNAME:-}" && -n "${REDHAT_REGISTRY_PASSWORD:-}" ]] \
    || registry_auth_file >/dev/null 2>&1
}

link_pull_secret() {
  oc secrets link default redhat-registry-pull --for=pull -n "$namespace" >/dev/null 2>&1 || true
}

rhaii_prereqs_met() {
  has_hf_secret && has_redhat_pull_secret
}

setup_rhaii_secrets() {
  if ! ensure_hf_secret; then
    echo "RHAII CPU deploy requires HF_TOKEN (env) or an existing hf-secret in ${namespace}." >&2
    echo "  export HF_TOKEN=hf_..." >&2
    return 1
  fi
  if ! ensure_redhat_pull_secret; then
    echo "RHAII CPU deploy requires registry.redhat.io pull credentials." >&2
    echo "  podman login registry.redhat.io" >&2
    echo "  # or set REDHAT_REGISTRY_USERNAME / REDHAT_REGISTRY_PASSWORD" >&2
    return 1
  fi
  link_pull_secret
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  setup_rhaii_secrets "$namespace"
  echo "OpenShift RHAII secrets ready in ${namespace}"
fi
