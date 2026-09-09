# OpenShift / Kubernetes deployment

Kustomize manifests for deploying the helpdesk email triage stack on OpenShift.

## Layout

```
deploy/openshift/
├── base/                         # Deployments, Services, PVC, ConfigMap, Secret
├── components/
│   ├── rhaii-cpu/                # RHAII 3.5 CPU inference (vllm-cpu-rhel9)
│   ├── routes/                   # OpenShift Routes (edge TLS, websocket timeout)
│   ├── route-reader/             # ServiceAccount + Role for Route auto-discovery
│   ├── network-policy/           # Namespace NetworkPolicies (default deny + allow rules)
│   └── hardening/                # Patches: REQUIRE_SECRETS, dashboard OAuth
└── overlays/
    ├── helpdesk-email-triage/         # Mock inference — existing project
    ├── helpdesk-email-triage-rhaii/   # RHAII CPU — existing project (recommended prod demo)
    ├── mock-demo/                     # Greenfield mock stack
    ├── rhaii-demo/                    # Greenfield RHAII CPU stack
    ├── gateway-only/                  # Integrator path (no UI)
    ├── external-inference/            # Gateway + inference Service elsewhere
    ├── hardened/                      # Production mock + hardening
    └── hardened-rhaii/              # Production RHAII CPU + hardening
```

Images default to `quay.io/mtahhan/helpdesk-*:latest`. Pin tags with `IMAGE_TAG=v1.2.3 make deploy-openshift` or Kustomize `images:` in your fork. RHAII CPU uses `registry.redhat.io/rhaii/vllm-cpu-rhel9:3.5.0-1786546771` (same as `compose.yml`).

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

Gateway CORS and Streamlit WebSocket settings are applied automatically at pod startup — no post-deploy patching. Deploy records inference mode and overlay in the `helpdesk-deploy-info` ConfigMap for reliable `undeploy-openshift`.

## Production / hardened overlay

For pilots beyond the demo defaults, use the hardened overlay (NetworkPolicies, OpenShift OAuth on the dashboard Route, `REQUIRE_SECRETS=1`):

```bash
export VAULT_SECRET="$(openssl rand -hex 32)"
export INGEST_API_KEY="$(openssl rand -hex 16)"
oc create secret generic helpdesk-secrets \
  --from-literal=VAULT_SECRET="$VAULT_SECRET" \
  --from-literal=INGEST_API_KEY="$INGEST_API_KEY" \
  -n helpdesk-email-triage --dry-run=client -o yaml | oc apply -f -

INFERENCE=rhaii OVERLAY=deploy/openshift/overlays/hardened make deploy-openshift
# maps hardened → hardened-rhaii when INFERENCE=rhaii
```

With `REQUIRE_SECRETS=1`, the gateway refuses to start with demo-default `VAULT_SECRET` or a missing `INGEST_API_KEY`. HTTP ingest then requires header `X-Ingest-Key`. Ticket JSON on the gateway PVC is not encrypted at rest — use an encrypted storage class for regulated data.

Full checklist: [docs/deploy-openshift.md](../../docs/deploy-openshift.md#production-checklist).

## Verify

```bash
make verify-openshift
```

This resolves Route URLs, checks gateway health and dashboard headers, waits for file-watcher tickets, and falls back to `/ingest/raw` if needed (reads `INGEST_API_KEY` from `helpdesk-secrets` when set).

Manual equivalent:

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

`undeploy-openshift` reads `helpdesk-deploy-info` to select the correct overlay and image tag.

## Auto-discovery

On OpenShift, both `email-gateway` and `agent-dashboard` entrypoints:

1. Read the in-cluster ServiceAccount token
2. Query `routes.route.openshift.io/agent-dashboard`
3. Set `DASHBOARD_ORIGIN` and `STREAMLIT_BROWSER_SERVER_ADDRESS` from the Route hostname

Streamlit XSRF protection is enabled automatically on OpenShift. Requires the `route-reader` component (included in demo overlays).

## Validate manifests locally

```bash
make validate-manifests
```

## Notes

- **Single gateway replica** — JSON ticket store on ReadWriteOnce PVC (`Recreate` strategy); not encrypted at rest.
- **RHAII CPU** — no GPU Operator; requires AVX2+ worker nodes (16 GiB+ allocatable RAM recommended) and `hf-secret` + `redhat-registry-pull`.
- **NetworkPolicies** — included in demo overlays; restrict pod-to-pod traffic within the namespace.
- **SMTP** — not exposed on public Routes; use authenticated `POST /ingest` for production MTA integration.
- **Rebuild images** after changing entrypoints; push to your registry before redeploying.

See [docs/deploy-openshift.md](../../docs/deploy-openshift.md).
