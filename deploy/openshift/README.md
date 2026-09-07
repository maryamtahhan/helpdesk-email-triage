# OpenShift / Kubernetes deployment

Kustomize manifests for deploying the helpdesk email triage stack on OpenShift (or any Kubernetes cluster with minor edits).

## Layout

```
deploy/openshift/
├── base/                         # Shared Deployments, Services, PVC, ConfigMap, Secret
├── components/routes/            # OpenShift Routes + CORS helper ConfigMap
└── overlays/
    ├── mock-demo/                # Mock inference + gateway + dashboard (demo / CI parity)
    ├── gateway-only/             # Mock inference + gateway (integrator path)
    └── external-inference/         # Gateway only, wired to your existing inference Service
```

Images default to `quay.io/mayamtahhan/helpdesk-*:latest`. Override in an overlay:

```yaml
images:
  - name: quay.io/mayamtahhan/helpdesk-email-gateway
    newName: registry.example.com/acme/helpdesk-email-gateway
    newTag: v1.0.0
```

## Prerequisites

- OpenShift 4.x or Kubernetes 1.27+ with a default StorageClass (for ticket PVC)
- `kubectl` and `kustomize` (or `oc kustomize`)
- Cluster pull access to your image registry
- For production inference: Red Hat AI Inference or another OpenAI-compatible endpoint

## Deploy (mock demo stack)

```bash
# Build manifests (sample emails reference repo paths; load restrictor required)
kustomize build --load-restrictor LoadRestrictionsNone deploy/openshift/overlays/mock-demo \
  | oc apply -f -

# Or with kubectl on plain Kubernetes (Routes require OpenShift CRD):
# kustomize build ... | kubectl apply -f -

oc wait deployment/inference-mock -n helpdesk-email-triage --for=condition=Available --timeout=180s
oc wait deployment/email-gateway -n helpdesk-email-triage --for=condition=Available --timeout=180s
oc wait deployment/agent-dashboard -n helpdesk-email-triage --for=condition=Available --timeout=180s

oc get route -n helpdesk-email-triage
```

Patch CORS after you know the dashboard Route URL:

```bash
DASHBOARD_URL="$(oc get route agent-dashboard -n helpdesk-email-triage -o jsonpath='{.spec.host}')"
oc patch configmap helpdesk-routes -n helpdesk-email-triage --type merge \
  -p "{\"data\":{\"DASHBOARD_ORIGIN\":\"https://${DASHBOARD_URL}\"}}"
oc rollout restart deployment/email-gateway -n helpdesk-email-triage
```

## Deploy (gateway only — integrator path)

```bash
kustomize build --load-restrictor LoadRestrictionsNone deploy/openshift/overlays/gateway-only \
  | oc apply -f -
```

Gateway listens on SMTP (`3025`) and HTTP (`8080`). See [docs/integration.md](../../docs/integration.md).

## Deploy (external inference — production pattern)

1. Run Red Hat AI Inference (or vLLM) in your cluster or on a reachable host.
2. Edit `overlays/external-inference/patch-external-inference.yaml` with your Service DNS name, or patch after apply:

```bash
kustomize build deploy/openshift/overlays/external-inference | oc apply -f -

oc patch configmap helpdesk-config -n helpdesk-email-triage --type merge -p '{
  "data": {
    "VLLM_BASE_URL": "http://rhaii.inference.svc.cluster.local:8000/v1",
    "VLLM_ENDPOINT": "http://rhaii.inference.svc.cluster.local:8000/v1/chat/completions"
  }
}'
```

3. Set a strong vault secret:

```bash
oc create secret generic helpdesk-secrets \
  --from-literal=VAULT_SECRET="$(openssl rand -hex 32)" \
  -n helpdesk-email-triage --dry-run=client -o yaml | oc apply -f -
```

## Validate locally

```bash
make validate-manifests
```

## Notes

- **Single replica:** ticket storage is a JSON file on a PVC; scale the gateway only after moving to shared storage.
- **SMTP in clusters:** prefer an MTA relay → `POST /ingest` rather than exposing port 3025 on a Route.
- **Podman alternative:** use `compose.mock.demo.yml`, `compose.gateway-only.yml`, or Quadlet units under `deploy/quadlet/`.

See [docs/deploy-openshift.md](../../docs/deploy-openshift.md) for a full runbook.
