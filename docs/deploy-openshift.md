# Deploy on OpenShift

This guide covers cluster deployment of the helpdesk email triage quickstart. For single-host RHEL, use Podman Compose or Quadlet (`deploy/quadlet/`).

## One-command deploy

```bash
oc new-project helpdesk-email-triage   # skip if project already exists
oc label namespace helpdesk-email-triage opendatahub.io/dashboard=true   # optional
make deploy-openshift
# or: ./scripts/deploy-openshift.sh helpdesk-email-triage
```

That applies the Kustomize overlay, waits for all Deployments, and prints the Route URLs. **No manual ConfigMap patching** — gateway and dashboard entrypoints discover the `agent-dashboard` Route hostname from the OpenShift API at startup (via a scoped ServiceAccount).

## Verify

Confirm workloads and routes:

```bash
oc get pods,route -n helpdesk-email-triage
```

Check the gateway health endpoint and dashboard Route (example on `apps.alpha.modelarch.org`):

```bash
curl -sk https://email-gateway-helpdesk-email-triage.apps.alpha.modelarch.org/health
curl -skI https://agent-dashboard-helpdesk-email-triage.apps.alpha.modelarch.org | head -5
```

Open: [https://agent-dashboard-helpdesk-email-triage.apps.alpha.modelarch.org](https://agent-dashboard-helpdesk-email-triage.apps.alpha.modelarch.org)

Expected gateway response: `{"status":"ok"}`. The dashboard `curl -I` should return `HTTP/1.1 200 OK`. Sample `.eml` files in the mounted ConfigMap should appear as tickets within a few seconds; the Streamlit queue auto-refreshes every 10 seconds.

Resolve hosts dynamically for other namespaces:

```bash
NS=helpdesk-email-triage
GW=$(oc get route email-gateway -n "$NS" -o jsonpath='{.spec.host}')
UI=$(oc get route agent-dashboard -n "$NS" -o jsonpath='{.spec.host}')

curl -sk "https://${GW}/health"
curl -skI "https://${UI}" | head -5
echo "Open: https://${UI}"
```

Optional ingest test:

```bash
curl -sk -X POST "https://${GW}/ingest/raw" \
  -H "Content-Type: application/json" \
  -d '{"sender":"test@example.com","subject":"Verify deploy","body":"OpenShift smoke test."}'
curl -sk "https://${GW}/tickets" | python3 -m json.tool | head -20
```

## Choose an overlay

| Overlay | Use when |
|---|---|
| `deploy/openshift/overlays/helpdesk-email-triage` | **Recommended** — deploy into an existing project (`oc new-project`) |
| `deploy/openshift/overlays/mock-demo` | Greenfield — Kustomize creates the Namespace resource |
| `deploy/openshift/overlays/gateway-only` | API/SMTP only; no Streamlit UI |
| `deploy/openshift/overlays/external-inference` | Gateway wired to existing RHAII / vLLM |

Set a custom overlay when calling the script:

```bash
OVERLAY=deploy/openshift/overlays/mock-demo ./scripts/deploy-openshift.sh my-namespace
```

## How auto-configuration works

| Concern | Mechanism |
|---|---|
| Streamlit WebSocket host | `agent-dashboard/entrypoint.sh` reads Route `agent-dashboard` |
| Gateway CORS (`DASHBOARD_ORIGIN`) | `email-gateway/entrypoint.sh` reads the same Route host |
| RBAC | `deploy/openshift/components/route-reader/` grants `get/list routes` in-namespace |

Optional override: set `DASHBOARD_ORIGIN` or `STREAMLIT_BROWSER_SERVER_ADDRESS` in the environment to skip auto-discovery.

**Images must include the entrypoints** — rebuild and push `helpdesk-email-gateway` and `helpdesk-triage-ui` after pulling these changes.

## Production checklist

1. **Images** — mirror or rebuild into your registry; update Kustomize `images:` in your overlay.
2. **Secrets** — replace `VAULT_SECRET` before any real deployment.
3. **Inference** — use `external-inference` overlay for existing RHAII.
4. **Storage** — gateway uses a 1 Gi PVC; single replica only unless you add shared storage.
5. **SMTP** — relay to `POST /ingest`; do not expose port 3025 on a public Route.

## Uninstall

Remove resources but keep the project:

```bash
make undeploy-openshift
# or: ./scripts/undeploy-openshift.sh helpdesk-email-triage
```

Delete the entire project:

```bash
DELETE_NAMESPACE=1 make undeploy-openshift
# or: oc delete project helpdesk-email-triage
```

## Kind / CI testing

For GitHub Actions and local Kubernetes testing without OpenShift:

```bash
make kind-e2e
```

See [deploy/kind/README.md](../deploy/kind/README.md).

## Related docs

- [Customer CI pipelines](customer-ci.md)
- [Integration guide](integration.md)
- [OpenShift manifest README](../deploy/openshift/README.md)
