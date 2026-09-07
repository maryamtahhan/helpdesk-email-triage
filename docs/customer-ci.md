# Customer CI and pipeline adoption

This repository is designed so you can fork it, point CI at your registry, and deploy with Podman Compose, Quadlet, or OpenShift Kustomize overlays without rewriting application code.

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
| `.github/workflows/ci.yml` | Unit tests, compose validation, manifest validation, compose e2e |
| `.github/workflows/publish-quay.yml` | Build, smoke-test, push images, Trivy scan |
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

Compose and Kustomize defaults use `quay.io/mayamtahhan/helpdesk-*`; override with env vars or Kustomize `images:`.

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

1. **Test** — `make test && make test-webhook`
2. **Validate manifests** — `make validate-manifests`
3. **Kind e2e** — `make kind-e2e` (plain Kubernetes; no cluster required beyond Docker)
4. **Build images** — build each `*/Containerfile` with your registry tag
5. **Smoke test** — run container with import check (see `publish-quay.yml`)
6. **Scan** — Trivy or your scanner on pushed images
7. **Deploy** — `make deploy-openshift` (or `kustomize build ... | oc apply -f -`)
8. **Verify** — health check + dashboard Route (see below)

Example Tekton-style steps map directly to the Makefile targets:

```bash
make test
make validate-manifests
# build & push images (podman or buildah)
make kind-e2e      # Kubernetes mock stack (runs in GitHub Actions)
make compose-e2e   # optional Podman/Docker compose gate
```

### Verify after OpenShift deploy

```bash
oc get pods,route -n helpdesk-email-triage

curl -sk https://email-gateway-helpdesk-email-triage.apps.alpha.modelarch.org/health
curl -skI https://agent-dashboard-helpdesk-email-triage.apps.alpha.modelarch.org | head -5
```

Open: [https://agent-dashboard-helpdesk-email-triage.apps.alpha.modelarch.org](https://agent-dashboard-helpdesk-email-triage.apps.alpha.modelarch.org)

See [deploy-openshift.md](deploy-openshift.md) for dynamic hostname resolution on other clusters.

## Local parity with CI

```bash
make test
make validate-manifests
make kind-e2e
make compose-e2e
```

## Versioning recommendation

- Tag releases as `v1.2.3` and set `IMAGE_TAG` to match.
- Pin overlay `images.newTag` to the same semver for reproducible cluster deploys.
- Keep `latest` for development only.

## Support matrix

| Environment | Supported path |
|---|---|
| RHEL + Podman Compose | `compose.yml`, `compose.mock.demo.yml`, `compose.gateway-only.yml` |
| RHEL + systemd | `deploy/quadlet/` |
| OpenShift 4.x | `deploy/openshift/overlays/*`, `make deploy-openshift` |
| Kind / Kubernetes CI | `deploy/kind/overlays/*`, `make run-on-kind`, `make kind-e2e`, `make destroy-kind` |
| Customer CI | GitHub Actions workflows + Makefile targets |
