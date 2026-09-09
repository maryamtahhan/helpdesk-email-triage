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

### RHAII CPU inference (production demo)

By default, `make deploy-openshift` uses **`INFERENCE=auto`**:

- If `HF_TOKEN` and `registry.redhat.io` credentials are available → deploys **RHAII CPU** (`vllm-cpu-rhel9`) in the same namespace as the gateway and UI
- Otherwise → deploys the **mock** inference pod (fast, no Red Hat registry)

```bash
podman login registry.redhat.io
export HF_TOKEN="your_huggingface_token"
make deploy-openshift
# equivalent: INFERENCE=rhaii make deploy-openshift
```

This follows [RHAII 3.5 standalone CPU on OpenShift](https://docs.redhat.com/en/documentation/red_hat_ai_inference/3.5/html/getting_started/about-cpu-inference_getting-started) — **CPU only, no GPU Operator**. The deploy script creates `hf-secret` and `redhat-registry-pull` in your project automatically.

Force mock (CI parity, no registry access):

```bash
INFERENCE=mock make deploy-openshift
```

First RHAII start downloads model weights into the `rhaii-model-cache` PVC (several minutes). Increase wait time if needed:

```bash
RHAII_WAIT_TIMEOUT=1200s make deploy-openshift
```

Worker nodes need **x86_64 with AVX2** and enough RAM (16 GiB minimum, 32 GiB recommended for `Qwen/Qwen2.5-1.5B-Instruct`).

## Verify

Route hostnames include the **OpenShift project name** (`{route}-{namespace}.apps.{cluster}`). Resolve them from the cluster — do not hardcode URLs.

```bash
make verify-openshift
```

Or manually:

```bash
NS=helpdesk-email-triage
GW=$(oc get route email-gateway -n "$NS" -o jsonpath='{.spec.host}')
UI=$(oc get route agent-dashboard -n "$NS" -o jsonpath='{.spec.host}')
curl -sk "https://${GW}/health"
curl -skI "https://${UI}" | head -5
echo "Open: https://${UI}"
```

Still seeing `*-mtahhan-quickstart.apps.*`? Delete the old project and redeploy into `helpdesk-email-triage`:

```bash
oc delete project mtahhan-quickstart
make deploy-openshift
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
| `deploy/openshift/overlays/helpdesk-email-triage` | **Mock inference** — existing project, no registry/HF token |
| `deploy/openshift/overlays/helpdesk-email-triage-rhaii` | **RHAII CPU inference** — full demo with `vllm-cpu-rhel9` (used by `INFERENCE=rhaii`) |
| `deploy/openshift/overlays/mock-demo` | Greenfield — Kustomize creates the Namespace resource |
| `deploy/openshift/overlays/rhaii-demo` | Greenfield — Namespace + RHAII CPU stack |
| `deploy/openshift/overlays/gateway-only` | API/SMTP only; no Streamlit UI |
| `deploy/openshift/overlays/external-inference` | Gateway wired to RHAII/vLLM **already running elsewhere** |
| `deploy/openshift/overlays/hardened` | Production-oriented: NetworkPolicies, OAuth on dashboard Route, `REQUIRE_SECRETS=1` |

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

1. **Overlay** — use `deploy/openshift/overlays/hardened` (NetworkPolicies, dashboard OAuth, `REQUIRE_SECRETS=1`).
2. **Images** — pin tags with `IMAGE_TAG=v1.2.3 make deploy-openshift` or update Kustomize `images:` in your fork.
3. **Secrets** — before deploy, patch `helpdesk-secrets` with non-demo `VAULT_SECRET` and `INGEST_API_KEY` (required when `REQUIRE_SECRETS=1`). HTTP ingest then requires header `X-Ingest-Key`.
4. **Vault storage** — `tickets.json` on the gateway PVC is **not encrypted at rest**; use an encrypted volume class or external store for regulated data.
5. **Inference** — `INFERENCE=auto` deploys RHAII CPU when creds exist; use `external-inference` only when inference runs in another namespace.
6. **Storage** — gateway uses a 1 Gi PVC; RHAII uses a 20 Gi `rhaii-model-cache` PVC; single replica only unless you add shared storage.
7. **SMTP** — relay to authenticated `POST /ingest` or `/ingest/raw`; do not expose port 3025 on a public Route. SMTP returns `250` before triage completes — use HTTP ingest when durability matters.

### Hardened deploy example

```bash
export VAULT_SECRET="$(openssl rand -hex 32)"
export INGEST_API_KEY="$(openssl rand -hex 16)"
oc create secret generic helpdesk-secrets \
  --from-literal=VAULT_SECRET="$VAULT_SECRET" \
  --from-literal=INGEST_API_KEY="$INGEST_API_KEY" \
  -n helpdesk-email-triage --dry-run=client -o yaml | oc apply -f -
OVERLAY=deploy/openshift/overlays/hardened ./scripts/deploy-openshift.sh helpdesk-email-triage
```

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

## Scripts

| Script | Purpose |
|---|---|
| `scripts/deploy-openshift.sh` | Deploy mock or RHAII CPU stack (`INFERENCE=auto\|mock\|rhaii`) |
| `scripts/undeploy-openshift.sh` | Remove deployed resources |
| `scripts/openshift-verify.sh` | Print Route URLs from cluster and run health checks |
| `scripts/openshift-rhaii-secrets.sh` | Create `hf-secret` and `redhat-registry-pull` |

Makefile wrappers: `make deploy-openshift`, `make verify-openshift`, `make undeploy-openshift`.

## Related docs

- [Customer CI pipelines](customer-ci.md)
- [Integration guide](integration.md)
- [OpenShift manifest README](../deploy/openshift/README.md)
