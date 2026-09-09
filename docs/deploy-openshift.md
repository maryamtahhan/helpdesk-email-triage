# Deploy on OpenShift

**Start here:** the [README](../README.md) has copy-paste deploy, verify, and hardened commands. This guide adds overlay reference and production checklist detail.

For single-host RHEL, use Podman Compose or Quadlet (`deploy/quadlet/`).

## Decision guide

| I want… | Command |
|---|---|
| Demo (auto: RHAII if creds exist, else mock) | `make deploy-openshift` |
| Demo mock only | `INFERENCE=mock make deploy-openshift` |
| Demo RHAII CPU | `INFERENCE=rhaii make deploy-openshift` |
| Hardened mock | `OVERLAY=deploy/openshift/overlays/hardened make deploy-openshift` |
| Hardened RHAII CPU | `INFERENCE=rhaii OVERLAY=deploy/openshift/overlays/hardened make deploy-openshift` |

### `INFERENCE` vs `OVERLAY`

| Variable | Controls |
|---|---|
| `INFERENCE` | Mock vs RHAII for secrets, `oc wait`, and deploy metadata when **no** `OVERLAY` is set (`auto` → RHAII if `HF_TOKEN` + registry creds exist, else mock). |
| `OVERLAY` | Which Kustomize tree is applied. **Takes precedence** over the default overlay implied by `INFERENCE`. |

`deploy/openshift/overlays/hardened` includes the **mock** stack. For hardened **RHAII CPU**, use `INFERENCE=rhaii` with that overlay (remapped to `hardened-rhaii`) or set `OVERLAY=deploy/openshift/overlays/hardened-rhaii` explicitly.

## One-command deploy

```bash
oc new-project helpdesk-email-triage   # skip if project already exists
oc label namespace helpdesk-email-triage opendatahub.io/dashboard=true   # optional
make deploy-openshift
# or: ./scripts/deploy-openshift.sh helpdesk-email-triage
```

Applies the overlay, waits for Deployments, prints Route URLs. Gateway CORS and Streamlit WebSockets are discovered from the `agent-dashboard` Route at pod startup — no manual ConfigMap patching.

### RHAII CPU prerequisites

```bash
podman login registry.redhat.io
export HF_TOKEN="your_huggingface_token"
make deploy-openshift
# or: INFERENCE=rhaii make deploy-openshift
```

Follows [RHAII 3.5 CPU on OpenShift](https://docs.redhat.com/en/documentation/red_hat_ai_inference/3.5/html/getting_started/about-cpu-inference_getting-started) — **CPU only, no GPU Operator**. The deploy script creates `hf-secret` and `redhat-registry-pull` automatically.

Force mock (no registry):

```bash
INFERENCE=mock make deploy-openshift
```

First RHAII start downloads weights to the `rhaii-model-cache` PVC (several minutes). Increase wait: `RHAII_WAIT_TIMEOUT=1200s make deploy-openshift`. Workers need **x86_64 + AVX2** and **16 GiB+ allocatable RAM** (32 GiB recommended).

**Gateway not Ready (`0/1`)** — if pod logs show `GET /health/ready HTTP/1.1" 404`, the published `helpdesk-email-gateway` image is older than the manifests. Rebuild and push the gateway image (`make build-images` + push to your registry), set `IMAGE_TAG`, and `oc rollout restart deployment/email-gateway`. Quick workaround: patch the readiness probe to `/health` (see `openshift_gateway_readiness_hint` in `scripts/openshift-lib.sh`).

## Verify

```bash
make verify-openshift
```

Checks health, dashboard headers, file-watcher tickets, and falls back to `/ingest/raw`. Reads `INGEST_API_KEY` from `helpdesk-secrets` when set.

## Quickstart walkthrough

After verify succeeds, follow the [README Quickstart walkthrough](../README.md#quickstart-walkthrough): submit tickets (UI, SMTP, or `curl`), review classification and redaction, check classification speed, run quality checks, and optionally benchmark inference. On hardened overlays, use the Route URLs from verify and include `X-Ingest-Key` on gateway API calls.

## Load test inference (GuideLLM)

After verify, benchmark `inference-mock` or `rhaii-cpu` using the in-cluster Job pattern from [How to deploy and benchmark vLLM with GuideLLM on Kubernetes](https://developers.redhat.com/articles/2025/12/24/how-deploy-and-benchmark-vllm-guidellm-kubernetes):

```bash
make guidellm-openshift
```

Creates a results PVC, runs `ghcr.io/vllm-project/guidellm:v0.5.0` against the internal Service (not the Route), and copies `benchmark-results.html` / `.json` to `./results/guidellm-openshift/`. See [README Quickstart walkthrough — Load testing](../README.md#load-testing).

Manual check:

```bash
NS=helpdesk-email-triage
GW=$(oc get route email-gateway -n "$NS" -o jsonpath='{.spec.host}')
UI=$(oc get route agent-dashboard -n "$NS" -o jsonpath='{.spec.host}')
curl -sk "https://${GW}/health"
echo "Open: https://${UI}"
```

## Overlay catalog

| Overlay | Inference | Use when |
|---|---|---|
| `helpdesk-email-triage` | Mock | Existing project, no HF/registry |
| `helpdesk-email-triage-rhaii` | RHAII CPU | Existing project, full RHAII demo |
| `mock-demo` | Mock | Greenfield — creates Namespace |
| `rhaii-demo` | RHAII CPU | Greenfield + RHAII |
| `gateway-only` | Mock | API/SMTP only, no UI |
| `external-inference` | External | Gateway only; inference elsewhere |
| `hardened` | Mock | Production hardening (`REQUIRE_SECRETS=1`) |
| `hardened-rhaii` | RHAII CPU | Production hardening + RHAII |

Custom overlay:

```bash
OVERLAY=deploy/openshift/overlays/mock-demo ./scripts/deploy-openshift.sh my-namespace
```

## Production checklist

1. **Overlay** — `hardened` (mock) or `hardened-rhaii` / `INFERENCE=rhaii OVERLAY=.../hardened` (RHAII).
2. **Secrets** — non-demo `VAULT_SECRET` and `INGEST_API_KEY` in `helpdesk-secrets` before deploy.
3. **Images** — `IMAGE_TAG=v1.2.3 make deploy-openshift` or Kustomize `images:` in your fork.
4. **Vault storage** — `tickets.json` on the gateway PVC is **not encrypted at rest**.
5. **SMTP** — disabled automatically when `REQUIRE_SECRETS=1`; prefer authenticated HTTP ingest.
6. **OAuth** — hardened overlays protect **both** gateway and dashboard Routes with OpenShift OAuth; the dashboard pod receives only `INGEST_API_KEY` (not `VAULT_SECRET`) and uses it for ticket list and vault rehydration.
7. **NetworkPolicy** — demo overlays apply ingress-only policies. GuideLLM adds `allow-guidellm-to-inference` egress when you run `make guidellm-openshift`. If your cluster enforces default-deny **egress**, allow DNS to `openshift-dns` / `kube-dns` (UDP/TCP port 53) and egress from `email-gateway` to inference on port 8000.

### Hardened deploy

```bash
export VAULT_SECRET="$(openssl rand -hex 32)"
export INGEST_API_KEY="$(openssl rand -hex 16)"
oc create secret generic helpdesk-secrets \
  --from-literal=VAULT_SECRET="$VAULT_SECRET" \
  --from-literal=INGEST_API_KEY="$INGEST_API_KEY" \
  -n helpdesk-email-triage --dry-run=client -o yaml | oc apply -f -

# Mock:
OVERLAY=deploy/openshift/overlays/hardened ./scripts/deploy-openshift.sh helpdesk-email-triage

# RHAII CPU (also HF_TOKEN + registry login):
INFERENCE=rhaii OVERLAY=deploy/openshift/overlays/hardened ./scripts/deploy-openshift.sh helpdesk-email-triage
```

## Auto-configuration

| Concern | Mechanism |
|---|---|
| Streamlit WebSocket host | `agent-dashboard/entrypoint.sh` reads Route `agent-dashboard` |
| Gateway CORS | `email-gateway/entrypoint.sh` reads the same Route host |
| RBAC | `components/route-reader/` grants `get/list routes` in-namespace |
| Undeploy | `helpdesk-deploy-info` ConfigMap records overlay (`applied-overlay`), inference mode, and image tag |
| Readiness | Gateway probes `GET /health`; init container waits for inference `/models`. `GET /health/ready` is available on freshly built gateway images. |

## Uninstall

```bash
make undeploy-openshift
DELETE_NAMESPACE=1 make undeploy-openshift   # delete entire project
```

## Kind / CI (no OpenShift)

```bash
make kind-e2e
```

See [deploy/kind/README.md](../deploy/kind/README.md).

## Scripts

| Script | Purpose |
|---|---|
| `scripts/deploy-openshift.sh` | Deploy (`INFERENCE=auto\|mock\|rhaii`) |
| `scripts/undeploy-openshift.sh` | Remove resources |
| `scripts/openshift-verify.sh` | Smoke test (`make verify-openshift`) |
| `scripts/openshift-rhaii-secrets.sh` | Create HF + registry secrets |
| `scripts/guidellm-openshift.sh` | GuideLLM benchmark Job (`make guidellm-openshift`) |
| `scripts/test-openshift-overlay.sh` | Overlay / `INFERENCE` consistency (`make test-openshift-overlay`) |
| `scripts/wait-for-tickets.sh` | Poll gateway until tickets appear (used by verify / e2e) |

## Related

- [README — OpenShift section](../README.md#openshift-quick-deploy)
- [Manifest layout](../deploy/openshift/README.md)
- [Customer CI](customer-ci.md)
- [Integration guide](integration.md)
