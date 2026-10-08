# Functional and end-to-end testing

Automated **regression**, **smoke**, and **scenario** checks for maintainers and CI. This is **not** the primary home for customer evaluation flows.

- **Deploy + hands-on + GuideLLM (performance benchmarking)** — [README](../README.md) Tracks 1–2 and [Load testing](../README.md#load-testing) (`make guidellm-openshift`, `make guidellm-quadlet`).
- **Mock UI walkthrough** — [CONTRIBUTING.md local mock](../CONTRIBUTING.md#local-mock-validation) and [testing-locally.md](../testing-locally.md).

Use this folder when you need repeatable pass/fail gates (unit tests, compose/kind e2e, OpenShift verify, Quadlet maintainer scenarios).

## Quick map

| Layer | What it exercises | Typical command | Needs running stack? |
|-------|-------------------|-----------------|----------------------|
| Unit / API | Gateway pipeline, tokenizer, store | `make test` | No |
| Lint | ruff, shellcheck | `make lint`, `make shellcheck` | No |
| Webhook sink | `TICKET_SINK` dispatch | `make test-webhook` | No |
| OpenShift manifests | Kustomize / overlay consistency | `make validate-manifests`, `make test-openshift-overlay` | No |
| Mock Compose E2E | Gateway + mock inference + ingest | `make compose-e2e` | Yes (script starts stack) |
| Kind E2E | Mock stack on Kubernetes | `make kind-e2e` | Yes (Docker + kind) |
| OpenShift smoke | Routes, health, ingest on cluster | `make verify-openshift` | Yes (cluster) |
| **RHEL Quadlet E2E** | Real RHAII + gateway ± UI on one host | `make quadlet-e2e` | Yes (RHEL + Podman) |
| Manual mock UI | Streamlit demo, screenshots | [testing-locally.md](../testing-locally.md) | Yes (`make demo`) |

GuideLLM **benchmarking** (sizing inference for a pilot) is documented in the [README Load testing](../README.md#load-testing) section, not here. The `full` Quadlet E2E scenario optionally runs a **short** GuideLLM smoke as part of the scenario.

## Guides in this folder

| Document | Contents |
|----------|----------|
| [automated-checks.md](automated-checks.md) | Workstation and CI targets (`test`, `lint`, `compose-e2e`, `kind-e2e`, webhooks) |
| [quadlet-e2e.md](quadlet-e2e.md) | Full automated scenarios on RHEL (maintainer E2E) |

## OpenShift validation

Checks that require an OpenShift cluster and (for RHAII paths) `registry.redhat.io` plus a Hugging Face token.

### Deploy and smoke test

```bash
INFERENCE=rhaii make deploy-openshift   # or INFERENCE=mock for mock-only
make verify-openshift
```

`verify-openshift` prints Route URLs and runs health / ticket checks. Details: [deploy-openshift.md](../deploy-openshift.md).

Manifest gates without a cluster: `make validate-manifests` and `make test-openshift-overlay` ([automated-checks.md](automated-checks.md)).

### GuideLLM (inference benchmarking)

**Canonical steps:** [README → Load testing](../README.md#load-testing) (`make guidellm-openshift` on OpenShift, `make guidellm-quadlet` on RHEL Quadlet). Use that section for image names, env vars, and reading HTML/JSON reports.

This folder covers **functional** OpenShift checks (`verify-openshift`), not pilot sizing benchmarks.

### Gateway load (not GuideLLM)

GuideLLM targets **inference** only. For parallel **gateway** ingest, use multiple `POST /ingest/raw` against the gateway Route; add `X-Ingest-Key` when hardened. See README [Load testing](../README.md#load-testing).

### Tear-down

```bash
make undeploy-openshift
# DELETE_NAMESPACE=1 make undeploy-openshift
```

## Customer vs maintainer

- **Customer evaluation** — README Tracks 1–2, [quickstart-walkthrough.md](../quickstart-walkthrough.md), and [Load testing / GuideLLM](../README.md#load-testing).
- **Maintainer / CI** — `make test`, `make compose-e2e`, and `make kind-e2e` on every PR ([customer-ci.md](../customer-ci.md)). **Quadlet E2E** on a RHEL host (not GitHub Actions today).

## Results artifacts (this folder’s tests)

| Path | Produced by |
|------|-------------|
| `results/quadlet-e2e/` | `make quadlet-e2e` |

GuideLLM report paths (`results/guidellm-openshift/`, `results/guidellm-quadlet/`) are listed in [README → Load testing](../README.md#step-3-review-results).

All under `results/` are gitignored.
