# OpenShift manifests

Kustomize layouts for the helpdesk email triage stack.

**Deploy commands and decision guide:** [README](../../README.md#openshift-quick-deploy) · **Runbook:** [docs/deploy-openshift.md](../../docs/deploy-openshift.md)

## Layout

```
deploy/openshift/
├── base/                    # Deployments, Services, PVC, ConfigMap, Secret
├── components/
│   ├── rhaii-cpu/           # RHAII 3.5 CPU (vllm-cpu-rhel9)
│   ├── routes/              # OpenShift Routes (edge TLS)
│   ├── route-reader/        # ServiceAccount for Route auto-discovery
│   ├── network-policy/      # Namespace NetworkPolicies + GuideLLM egress
│   └── hardening/           # REQUIRE_SECRETS, OAuth on Routes, scoped dashboard secrets
└── overlays/
    ├── helpdesk-email-triage/       # Mock — existing project
    ├── helpdesk-email-triage-rhaii/ # RHAII — existing project
    ├── mock-demo/                   # Mock — creates Namespace
    ├── rhaii-demo/                  # RHAII — creates Namespace
    ├── gateway-only/
    ├── external-inference/
    ├── hardened/                    # Mock + hardening
    └── hardened-rhaii/              # RHAII + hardening
```

Images default to `quay.io/mtahhan/helpdesk-*:latest`. Pin with `IMAGE_TAG=v1.2.3 make deploy-openshift`. RHAII image: `registry.redhat.io/rhaii/vllm-cpu-rhel9:3.5.0-1786546771`.

## Overlay quick reference

| Overlay | Inference pod |
|---|---|
| `helpdesk-email-triage`, `mock-demo`, `hardened` | `inference-mock` |
| `helpdesk-email-triage-rhaii`, `rhaii-demo`, `hardened-rhaii` | `rhaii-cpu` |

`OVERLAY=.../hardened` deploys mock unless `INFERENCE=rhaii` (remapped to `hardened-rhaii`).

## Validate locally

```bash
make validate-manifests
```

## Hardening (`components/hardening/`)

Used by `hardened` and `hardened-rhaii` overlays:

| Patch | Effect |
|---|---|
| `patch-require-secrets.yaml` | `REQUIRE_SECRETS=1` — non-demo secrets required; SMTP disabled |
| `patch-route-gateway-oauth.yaml` | OpenShift OAuth on the gateway Route |
| `patch-route-dashboard-oauth.yaml` | OpenShift OAuth on the dashboard Route |
| `patch-dashboard-scope-secrets.yaml` | Dashboard pod gets `INGEST_API_KEY` only (vault via `X-Ingest-Key`) |

## GuideLLM benchmark

`make guidellm-openshift` benchmarks **RHAII only** (`rhaii-cpu`). It applies `components/network-policy/allow-guidellm-to-inference.yaml`, runs a Job with `ghcr.io/vllm-project/guidellm:v0.5.0`, and copies results to `./results/guidellm-openshift/`. Not available on mock-only overlays. See [docs/deploy-openshift.md](../../docs/deploy-openshift.md#load-test-inference-guidellm).

## Notes

- Gateway uses a 1 Gi ReadWriteOnce PVC (`Recreate` strategy); ticket JSON is not encrypted at rest.
- Gateway readiness probe: `GET /health` (init container waits for inference `/models`). `GET /health/ready` for deeper checks after republishing the gateway image.
- RHAII needs `hf-secret` + `redhat-registry-pull` and workers with 16 GiB+ allocatable RAM.
- NetworkPolicies ship with demo overlays; GuideLLM adds egress to inference when benchmarking.
- Rebuild and push gateway/UI images after entrypoint changes.
