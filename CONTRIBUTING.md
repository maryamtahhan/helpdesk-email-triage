# Contributing

This guide is for **maintainers and contributors** working on the quickstart itself — local mock stacks, CI, and development workflows. Customer evaluation paths stay in the [README](README.md) (OpenShift and RHEL Quadlet with RHAII 3.5 CPU).

**Authors:** Maryam Tahhan · Anton Ivanov · Michael Dawson

## Local mock validation

*~15 minutes. **Not a customer evaluation path** — uses a mock classifier and needs no Red Hat registry login or Hugging Face token. Use for UI smoke tests, docs screenshots, and `make compose-e2e` / CI.*

### Prerequisites

- `podman` or `docker` with Compose, `make`, `curl`, `python3`
- On RHEL when `podman compose` is missing: `sudo dnf install -y git make python-pip` then `pip3 install --user podman-compose` (add `~/.local/bin` to `PATH`)

### Step 1: Start the mock stack

```bash
git clone https://github.com/rh-ai-quickstart/helpdesk-email-triage && cd helpdesk-email-triage
make demo
```

Gateway `:8080`, dashboard `:8501`, SMTP `:3025`. Sample mail ingests automatically. Welcome pill shows **local mock**.

```bash
curl -sS http://127.0.0.1:8080/health   # classify_model: mock-triage
```

### Step 2: Smoke-test the inbox

Walk the Track 1 checklist in the [README](README.md#submit-support-tickets) ([Submit support tickets](README.md#submit-support-tickets) through redaction) at `http://127.0.0.1:8501/welcome`. Vault demo secret: `helpdesk-demo-secret`. Skip [Load testing](README.md#load-testing) unless you run `compose.yml` with RHAII.

Optional maintainer checks: stop mock inference (`podman stop helpdesk-email-triage-inference-mock`) and confirm **heuristic-fallback** ingest.

```bash
make down
```

For an API-only local stack without the dashboard, run `make gateway-only`. It also uses mock inference.

## OpenShift smoke deployment with mock inference

Use this deployment for overlay and CI smoke checks, or when a cluster is not ready to run RHAII. It is not a customer evaluation path; use the RHAII deployment in the [README](README.md#track-1-deploy-to-openshift-rhaii-cpu) for that.

```bash
INFERENCE=mock make deploy-openshift
```

For a hardened-overlay smoke check:

```bash
INFERENCE=mock OVERLAY=deploy/openshift/overlays/hardened make deploy-openshift
```

Set `INFERENCE=mock` explicitly to test the hardened overlay with mock inference. For RHAII, set `INFERENCE=rhaii`; the deploy script maps the hardened overlay to `hardened-rhaii`. `INFERENCE` defaults to `rhaii`; `INFERENCE=auto` selects RHAII when its registry and model credentials are available, and mock inference otherwise. The mock deployment does not need RHAII registry or Hugging Face credentials.

The dashboard welcome page identifies this as **local mock**, and `/health` reports `mock-triage`. GuideLLM benchmarks require the RHAII inference endpoint and do not apply to mock-only deployments.

## Development

The OpenAI-compatible inference stub is in `inference-mock/`; its configured model name is `mock-triage`.

```bash
make test              # unit tests (no running stack)
make lint
make compose-e2e       # mock gateway stack smoke test
make validate-manifests
make test-openshift-overlay
make build-images
```

**GuideLLM** (inference benchmarking for customers): [README — Load testing](README.md#load-testing).

**Functional / E2E regression:** [docs/testing/README.md](docs/testing/README.md).

**CI** (on every PR): ruff, tests, compose e2e, kind e2e, container builds (mock inference only).

**Published images:** `quay.io/rh-ai-quickstart/helpdesk-email-triage-email-gateway`, `helpdesk-email-triage-ui`, `helpdesk-email-triage-inference-mock`.
