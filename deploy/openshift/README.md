# OpenShift / Kubernetes deployment

Kustomize manifests for deploying the helpdesk email triage stack on OpenShift.

## Layout

```
deploy/openshift/
├── base/                         # Deployments, Services, PVC, ConfigMap, Secret
├── components/
│   ├── routes/                   # OpenShift Routes (edge TLS, websocket timeout)
│   └── route-reader/             # ServiceAccount + Role for Route auto-discovery
└── overlays/
    ├── helpdesk-email-triage/    # Recommended: existing project (no Namespace resource)
    ├── mock-demo/                # Greenfield: creates Namespace + full demo stack
    ├── gateway-only/             # Integrator path (no UI)
    └── external-inference/       # Gateway + external RHAII
```

Images default to `quay.io/mtahhan/helpdesk-*:latest`.

## Deploy (recommended)

```bash
oc new-project helpdesk-email-triage   # once
oc label namespace helpdesk-email-triage opendatahub.io/dashboard=true   # optional
make deploy-openshift
```

Or manually:

```bash
kustomize build --load-restrictor LoadRestrictionsNone \
  deploy/openshift/overlays/helpdesk-email-triage | oc apply -f -

oc wait deployment --all -n helpdesk-email-triage --for=condition=Available --timeout=300s
oc get route -n helpdesk-email-triage
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

Requires the `route-reader` component (included in `mock-demo` and `helpdesk-email-triage` overlays).

## Validate manifests locally

```bash
make validate-manifests
```

## Notes

- **Single gateway replica** — JSON ticket store on ReadWriteOnce PVC (`Recreate` strategy).
- **Rebuild images** after changing entrypoints; push to your registry before redeploying.

See [docs/deploy-openshift.md](../../docs/deploy-openshift.md).
