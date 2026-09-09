# Customer CI and pipeline adoption

**Deploy and verify commands:** [README](../README.md) · **OpenShift overlays:** [deploy-openshift.md](deploy-openshift.md)

Fork this repository, point CI at your registry, and deploy with Podman Compose, Quadlet, or OpenShift Kustomize without rewriting application code.

## Reusable components

| Component | Path | Deploy as |
|---|---|---|
| Email gateway (API + SMTP + tokenization) | `email-gateway/` | Container / OpenShift Deployment |
| Streamlit demo inbox | `agent-dashboard/` | Optional UI container |
| Mock inference (laptop / test) | `inference-mock/` | Optional; replace with RHAII in prod |
| OpenShift manifests | `deploy/openshift/overlays/*` | `kustomize build \| oc apply` |
| Podman Compose | `compose*.yml` | `podman compose up` |
| Quadlet (systemd) | `deploy/quadlet/` | RHEL single-host |

The gateway exposes a stable HTTP contract documented in [integration.md](integration.md). Downstream systems integrate via `GET /tickets`, `POST /ingest`, SMTP, or `TICKET_SINK` webhooks.

## Fork workflow

1. Fork the repository into your org.
2. Create three image repositories in your registry (gateway, UI, mock).
3. Set CI secrets (see below).
4. Customize image names in:
   - `.env.example` / compose files
   - `deploy/openshift/overlays/*/kustomization.yaml` (`images:` transformer)
5. Deploy with your chosen overlay or compose file.

## GitHub Actions (included)

| Workflow | Purpose |
|---|---|
| `.github/workflows/ci.yml` | ruff lint, unit tests, compose validation, Kustomize validation (pinned), container builds + Trivy scan, compose e2e, kind e2e |
| `.github/workflows/publish-quay.yml` | Lint, tests, compose e2e, then build, smoke-test, and push images |
| `.github/workflows/reusable-build.yml` | Callable workflow for customer repos |

### Secrets for publish

| Secret | Purpose |
|---|---|
| `REDHAT_REGISTRY_USERNAME` | Registry robot account (Quay or other) |
| `REDHAT_REGISTRY_PASSWORD` | Robot token |

### Customize registry namespace

In `publish-quay.yml` (or when calling the reusable workflow):

```yaml
env:
  IMAGE_REGISTRY: quay.io
  IMAGE_NAMESPACE: your-org
  IMAGE_TAG: latest
```

Compose and Kustomize defaults use `quay.io/mtahhan/helpdesk-*`; override with env vars or Kustomize `images:`.

## Reusable build workflow (call from your repo)

```yaml
jobs:
  publish:
    uses: your-org/helpdesk-email-triage/.github/workflows/reusable-build.yml@main
    secrets:
      REGISTRY_USERNAME: ${{ secrets.REGISTRY_USERNAME }}
      REGISTRY_PASSWORD: ${{ secrets.REGISTRY_PASSWORD }}
    with:
      image_registry: quay.io
      image_namespace: your-org
      image_tag: v1.0.0
      push: true
```

## OpenShift / Tekton / Jenkins

Minimal stages any pipeline should include:

1. **Lint** — `make lint`
2. **Test** — `make test && make test-webhook`
3. **Validate manifests** — `make validate-manifests`
4. **Kind e2e** — `make kind-e2e` (plain Kubernetes; no cluster required beyond Docker)
5. **Build images** — build each `*/Containerfile` with your registry tag
6. **Smoke test** — run container with import check (see `publish-quay.yml`)
7. **Scan** — Trivy is included in `ci.yml`; add your org scanner on push if required
8. **Deploy** — `make deploy-openshift` (production: `OVERLAY=.../hardened` for mock, or `INFERENCE=rhaii OVERLAY=.../hardened` for RHAII CPU)
9. **Verify** — `make verify-openshift` (health + ingest/ticket smoke test)

## OpenShift deploy

Customer clusters typically use:

```bash
export HF_TOKEN=...                      # for RHAII CPU path
podman login registry.redhat.io
make deploy-openshift                      # INFERENCE=auto
make verify-openshift
```

Use `INFERENCE=mock` in CI-like environments without registry access. For production pilots, use `hardened` (mock) or `hardened-rhaii` / `INFERENCE=rhaii OVERLAY=.../hardened` (RHAII CPU), and set non-demo `VAULT_SECRET` + `INGEST_API_KEY` before deploy. See [deploy-openshift.md](deploy-openshift.md#inference-vs-overlay).

Example Tekton-style steps map directly to the Makefile targets:

```bash
make lint
make test
make validate-manifests
# build & push images (podman or buildah)
make kind-e2e      # Kubernetes mock stack (runs in GitHub Actions)
make compose-e2e   # mock compose gate (not real RHAII / compose.yml)
```

### Verify after OpenShift deploy

```bash
make verify-openshift
```

See [deploy-openshift.md](deploy-openshift.md).

## Local parity with CI

```bash
make lint
make test
make validate-manifests
make kind-e2e
make compose-e2e
```

## Versioning recommendation

- Tag releases as `v1.2.3` and set `IMAGE_TAG` to match.
- Pin overlay `images.newTag` to the same semver for reproducible cluster deploys, or pass `IMAGE_TAG=v1.2.3` to `deploy-openshift.sh`.
- Keep `latest` for development only.

## Support matrix

| Environment | Supported path |
|---|---|
| RHEL + Podman Compose | `compose.yml`, `compose.mock.demo.yml`, `compose.gateway-only.yml` |
| RHEL + systemd | `deploy/quadlet/` |
| OpenShift 4.x | `deploy/openshift/overlays/*`, `make deploy-openshift` |
| Kind / Kubernetes CI | `deploy/kind/overlays/*`, `make run-on-kind`, `make kind-e2e`, `make destroy-kind` |
| Customer CI | GitHub Actions workflows + Makefile targets |
