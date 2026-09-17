# Automated checks (workstation and CI)

Commands you can run **without** a RHEL evaluation host or OpenShift cluster. These match the main [CI workflow](../../.github/workflows/ci.yml) gates.

## Unit tests

```bash
make test
```

Runs `pytest` under `email-gateway/tests` (pipeline, API, tokenizer, store). No containers required.

## Lint and shell scripts

```bash
make lint        # ruff on email-gateway, agent-dashboard, inference-mock
make shellcheck  # scripts/*.sh (warning level)
```

## Webhook sink

```bash
make test-webhook
```

Starts a local receiver and exercises `TICKET_SINK` dispatch without Compose. See [integration.md](../integration.md#webhook-sink).

## Mock Compose end-to-end

```bash
make compose-e2e
```

Uses `compose.gateway-only.yml` (mock inference, no Streamlit):

1. Brings the stack up
2. Waits for `GET /health`
3. Waits for tickets from the file watcher or falls back to `POST /ingest/raw`
4. Tears the stack down

This validates the **gateway path** only, not real RHAII.

## Kind end-to-end

```bash
make kind-e2e
```

Deploys the mock overlay to a local kind cluster, smoke-tests the gateway, destroys the cluster. See [deploy/kind/README.md](../../deploy/kind/README.md).

## OpenShift manifest consistency (no cluster)

```bash
make validate-manifests
make test-openshift-overlay
```

Ensures Kustomize builds and `INFERENCE` overlay wiring stay consistent.

## Adopting in your pipeline

See [customer-ci.md](../customer-ci.md) for a full stage list (lint → test → validate → kind-e2e → deploy → verify).
