# OpenShift / Kubernetes deployment

Kustomize manifests for deploying the helpdesk email triage stack on OpenShift.

## Layout

```
deploy/openshift/
├── base/                         # Deployments, Services, PVC, ConfigMap, Secret
├── components/
│   ├── rhaii-cpu/                # RHAII 3.5 CPU inference (vllm-cpu-rhel9)
│   ├── routes/                   # OpenShift Routes (edge TLS, websocket timeout)
│   └── route-reader/             # ServiceAccount + Role for Route auto-discovery
└── overlays/
    ├── helpdesk-email-triage/         # Mock inference — existing project
    ├── helpdesk-email-triage-rhaii/   # RHAII CPU — existing project (recommended prod demo)
    ├── mock-demo/                     # Greenfield mock stack
    ├── rhaii-demo/                    # Greenfield RHAII CPU stack
    ├── gateway-only/                  # Integrator path (no UI)
    └── external-inference/            # Gateway + inference Service elsewhere
```

Images default to `quay.io/mtahhan/helpdesk-*:latest`. RHAII CPU uses `registry.redhat.io/rhaii/vllm-cpu-rhel9:3.5.0-1786546771` (same as `compose.yml`).

## Deploy (recommended)

```bash
oc new-project helpdesk-email-triage   # once
oc label namespace helpdesk-email-triage opendatahub.io/dashboard=true   # optional

# RHAII CPU when HF_TOKEN + registry.redhat.io login are set; otherwise mock
export HF_TOKEN="your_huggingface_token"
podman login registry.redhat.io
make deploy-openshift
```

Or manually (RHAII CPU):

```bash
export HF_TOKEN=...
./scripts/openshift-rhaii-secrets.sh helpdesk-email-triage
kustomize build --load-restrictor LoadRestrictionsNone \
  deploy/openshift/overlays/helpdesk-email-triage-rhaii | oc apply -f -

oc wait deployment/rhaii-cpu deployment/email-gateway deployment/agent-dashboard \
  -n helpdesk-email-triage --for=condition=Available --timeout=900s
```

Gateway CORS and Streamlit WebSocket settings are applied automatically at pod startup — no post-deploy patching.

## Verify

```bash
oc get pods,route -n helpdesk-email-triage

curl -sk https://email-gateway-helpdesk-email-triage.apps.alpha.modelarch.org/health
curl -skI https://agent-dashboard-helpdesk-email-triage.apps.alpha.modelarch.org | head -5
```

Open: [https://agent-dashboard-helpdesk-email-triage.apps.alpha.modelarch.org](https://agent-dashboard-helpdesk-email-triage.apps.alpha.modelarch.org)

Dynamic hostnames (any namespace):

```bash
NS=helpdesk-email-triage
GW=$(oc get route email-gateway -n "$NS" -o jsonpath='{.spec.host}')
UI=$(oc get route agent-dashboard -n "$NS" -o jsonpath='{.spec.host}')
curl -sk "https://${GW}/health"
curl -skI "https://${UI}" | head -5
echo "Open: https://${UI}"
```

## Cleanup

```bash
make undeploy-openshift                  # remove resources, keep project
DELETE_NAMESPACE=1 make undeploy-openshift   # delete entire project
```

## Auto-discovery

On OpenShift, both `email-gateway` and `agent-dashboard` entrypoints:

1. Read the in-cluster ServiceAccount token
2. Query `routes.route.openshift.io/agent-dashboard`
3. Set `DASHBOARD_ORIGIN` and `STREAMLIT_BROWSER_SERVER_ADDRESS` from the Route hostname

Requires the `route-reader` component (included in demo overlays).

## Validate manifests locally

```bash
make validate-manifests
```

## Notes

- **Single gateway replica** — JSON ticket store on ReadWriteOnce PVC (`Recreate` strategy).
- **RHAII CPU** — no GPU Operator; requires AVX2+ worker nodes and `hf-secret` + `redhat-registry-pull`.
- **Rebuild images** after changing entrypoints; push to your registry before redeploying.

See [docs/deploy-openshift.md](../../docs/deploy-openshift.md).
