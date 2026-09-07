# Deploy on OpenShift

This guide covers cluster deployment of the helpdesk email triage quickstart. For single-host RHEL, use Podman Compose or Quadlet (`deploy/quadlet/`).

## Choose an overlay

| Overlay | Use when |
|---|---|
| `deploy/openshift/overlays/mock-demo` | Demo, CI parity, or clusters without RHAII |
| `deploy/openshift/overlays/gateway-only` | You consume tickets via API/webhook; no Streamlit UI |
| `deploy/openshift/overlays/external-inference` | Production: gateway wired to existing RHAII / vLLM |

All overlays live under `deploy/openshift/` and are built with Kustomize.

## Quick start (mock demo)

```bash
kustomize build --load-restrictor LoadRestrictionsNone \
  deploy/openshift/overlays/mock-demo | oc apply -f -

oc get pods,route -n helpdesk-email-triage
```

Open the `agent-dashboard` Route in a browser. If the UI loads but vault requests fail with CORS errors, patch `helpdesk-routes` with the dashboard Route URL (see `deploy/openshift/README.md`).

## Production checklist

1. **Images** — mirror or rebuild the three Containerfiles into your registry; update the `images:` block in your overlay fork.
2. **Secrets** — replace `VAULT_SECRET` (and `TICKET_SINK_SECRET` if using webhooks). Never ship the demo default.
3. **Inference** — use `external-inference` overlay; ensure the gateway can reach your OpenAI-compatible endpoint on the cluster network.
4. **Storage** — `gateway-data` PVC holds ticket JSON; size for expected volume (default 1 Gi).
5. **SMTP** — do not expose SMTP on a public Route; relay mail to `POST /ingest` or an internal Service.
6. **Scaling** — one gateway replica unless you replace the file store with shared storage.
7. **RHAII pull secret** — if you deploy RHAII in-cluster, create `imagePullSecrets` for `registry.redhat.io` (not included here; run inference as a separate chart or operator).

## Wiring external Red Hat AI Inference

The quickstart does not bundle an RHAII Helm chart. Typical enterprise layout:

```
[ MTA / case mgmt ] → email-gateway Deployment → RHAII Service (existing)
                              ↓
                      TICKET_SINK webhook → ServiceNow / Salesforce
```

Patch inference URLs on the `helpdesk-config` ConfigMap, then restart the gateway Deployment.

## Podman on RHEL (same artifacts, no cluster)

| Goal | Command |
|---|---|
| Full demo | `podman compose -f compose.mock.demo.yml up --build` |
| Integrator API only | `podman compose -f compose.gateway-only.yml up --build` |
| systemd user units | `deploy/quadlet/README.md` |

Compose and OpenShift manifests share the same container images and environment variable names (see `.env.example`).

## Uninstall

```bash
oc delete namespace helpdesk-email-triage
```

Or delete individual resources if you applied into an existing namespace (remove the `namespace:` field from the overlay first).

## Related docs

- [Customer CI pipelines](customer-ci.md)
- [Integration guide](integration.md)
- [OpenShift manifest README](../deploy/openshift/README.md)
