# OpenShift manifests

Kustomize layouts for the helpdesk email triage stack.

**Deploy commands and decision guide:** [README](../../README.md#openshift--kubernetes) · **Runbook:** [docs/deploy-openshift.md](../../docs/deploy-openshift.md)

## Layout

```
deploy/openshift/
├── base/                    # Deployments, Services, PVC, ConfigMap, Secret
├── components/
│   ├── rhaii-cpu/           # RHAII 3.5 CPU (vllm-cpu-rhel9)
│   ├── routes/              # OpenShift Routes (edge TLS)
│   ├── route-reader/        # ServiceAccount for Route auto-discovery
│   ├── network-policy/      # Namespace NetworkPolicies
│   └── hardening/           # REQUIRE_SECRETS + dashboard OAuth patches
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

## Notes

- Gateway uses a 1 Gi ReadWriteOnce PVC (`Recreate` strategy); ticket JSON is not encrypted at rest.
- RHAII needs `hf-secret` + `redhat-registry-pull` and workers with 16 GiB+ allocatable RAM.
- NetworkPolicies ship with demo overlays.
- Rebuild and push gateway/UI images after entrypoint changes.
