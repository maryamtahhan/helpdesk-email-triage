#!/usr/bin/env bash
# Validate OpenShift/Kustomize manifests (build + optional schema check).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OVERLAYS=(
  deploy/openshift/overlays/mock-demo
  deploy/openshift/overlays/rhaii-demo
  deploy/openshift/overlays/gateway-only
  deploy/openshift/overlays/external-inference
  deploy/openshift/overlays/helpdesk-email-triage
  deploy/openshift/overlays/helpdesk-email-triage-rhaii
  deploy/openshift/overlays/hardened
  deploy/kind/overlays/mock-demo
)

if ! command -v kustomize >/dev/null 2>&1; then
  echo "kustomize not found; install from https://kubectl.docs.kubernetes.io/installation/kustomize/" >&2
  exit 1
fi

for overlay in "${OVERLAYS[@]}"; do
  echo "==> kustomize build ${overlay}"
  kustomize build --load-restrictor LoadRestrictionsNone "${ROOT}/${overlay}" >/dev/null
done

if command -v kubeconform >/dev/null 2>&1; then
  for overlay in "${OVERLAYS[@]}"; do
    echo "==> kubeconform ${overlay}"
    kustomize build --load-restrictor LoadRestrictionsNone "${ROOT}/${overlay}" \
      | kubeconform -summary -ignore-missing-schemas \
        -schema-location default \
        -schema-location 'https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master/{{.NormalizedKubernetesVersion}}-standalone{{.Strict}}-{{.ResourceKind}}{{.KindSuffix}}.json' \
        -schema-location 'https://raw.githubusercontent.com/openshift/kubernetes-json-schema/main/{{.NormalizedKubernetesVersion}}-standalone{{.Strict}}-{{.ResourceKind}}{{.KindSuffix}}.json'
  done
else
  echo "kubeconform not installed; skipped schema validation"
fi

echo "OpenShift manifest validation passed."
