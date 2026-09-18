# Quadlet validation (RHEL maintainer E2E)

Automated scenario tests for **rootless Podman + user systemd** on RHEL 9.4+. This is **not** a customer install guide — use [deploy/quadlet/README.md](../../deploy/quadlet/README.md) for that.

## When to run

- After changing Quadlet units, gateway/dashboard images, or quadlet scripts
- Before tagging a release or demoing on a fresh EC2 host
- After `git pull` on your evaluation server

## Prerequisites

```bash
sudo dnf install -y podman git make
podman login registry.redhat.io
```

- Prod images: `make quadlet-build`
- **`~/.config/helpdesk/secrets.env`** with a **real** `HUGGING_FACE_HUB_TOKEN` (not `hf_your_token_here`)
- **≥16 GiB RAM** (32 GiB recommended for RHAII CPU)
- User systemd session (`systemctl --user` works over SSH)

```bash
# Example — use vi on minimal AMIs (no nano)
vi ~/.config/helpdesk/secrets.env
chmod 600 ~/.config/helpdesk/secrets.env
```

Accept the Qwen model license on huggingface.co if this is a fresh host.

## `QUADLET_ALLOW_PLACEHOLDER_SECRETS`

E2E and `make quadlet-up` treat `hf_your_token_here` in `secrets.env` as invalid.

| Value | Meaning |
|-------|---------|
| unset (default) | **Fail** preflight if the placeholder is still present — use a real Hugging Face token |
| `1` | Allow the placeholder for **smoke** runs when weights are already in `~/rhaii-cache` |

```bash
QUADLET_ALLOW_PLACEHOLDER_SECRETS=1 make quadlet-e2e
```

Effects when set to `1`:

- Preflight passes with the README template token.
- E2E sets `QUADLET_E2E_REQUIRE_MODEL=0` (ingest will not fail solely because `model` is `heuristic-fallback`).

Still required for full validation:

- Real token for first-time model download and for **`make guidellm-quadlet`** inside the `full` scenario.
- Customer evaluation should **not** rely on this flag.

Full reference: [deploy/quadlet/README.md — secrets.env](../../deploy/quadlet/README.md#secretsenv-and-quadlet_allow_placeholder_secrets).

## Run all scenarios

```bash
cd helpdesk-email-triage
make quadlet-build    # required once per host (or QUADLET_E2E_BUILD=1 make quadlet-e2e)
make quadlet-e2e
```

Default order: **`full`** → **`gateway-only`**. Each scenario stops services and clears `tickets.json` when finished.

### Scenarios

| Scenario | Stack | Checks |
|----------|--------|--------|
| `full` | RHAII + gateway + Streamlit | Inference `/v1/models`, gateway `/health/ready`, dashboard `/welcome`, `POST /ingest/raw` (expects real model), file watcher on `~/helpdesk/sample_emails`, short **GuideLLM**, teardown |
| `gateway-only` | RHAII + gateway (no UI) | `:8501` not serving, gateway ready, HTTP ingest, `GET /tickets`, teardown |

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `QUADLET_E2E_SCENARIOS` | `full,gateway-only` | Comma-separated scenario names |
| `QUADLET_E2E_SKIP_GUIDELLM` | `0` | `1` = skip GuideLLM in `full` (faster) |
| `QUADLET_E2E_GUIDELLM_SECONDS` | `90` | Short benchmark duration |
| `QUADLET_E2E_GUIDELLM_RATE` | `1` | Single concurrent stream |
| `QUADLET_E2E_BUILD` | `0` | `1` = run `quadlet-build` first |
| `QUADLET_E2E_INITIAL_RESET` | `0` | `1` = `quadlet-reset` + `quadlet-setup` before tests |
| `QUADLET_E2E_REQUIRE_MODEL` | `1` | Fail if ingest returns `heuristic-fallback` |
| `QUADLET_ALLOW_PLACEHOLDER_SECRETS` | unset | `1` = allow `hf_your_token_here`; relaxes E2E model assertion (see section above) |
| `RHAII_WAIT_TIMEOUT` | `900` | Max wait for inference boot |

Examples:

```bash
QUADLET_E2E_SKIP_GUIDELLM=1 make quadlet-e2e
QUADLET_E2E_SCENARIOS=gateway-only make quadlet-e2e
QUADLET_E2E_INITIAL_RESET=1 QUADLET_E2E_BUILD=1 make quadlet-e2e
QUADLET_ALLOW_PLACEHOLDER_SECRETS=1 QUADLET_E2E_SKIP_GUIDELLM=1 make quadlet-e2e   # smoke only
```

## Reports and exit codes

- **JSON summary:** `results/quadlet-e2e/report-<timestamp>.json` (per-step PASS/FAIL per scenario)
- **GuideLLM (full scenario):** `results/quadlet-e2e/full/guidellm/benchmark-results.html`
- Exit **0** only if every scenario status is `pass`

If preflight fails (placeholder secrets), the orchestrator prints setup instructions and still writes failed scenario entries to the report when possible.

## GuideLLM

The **`full`** scenario runs a **short** GuideLLM check when `QUADLET_E2E_SKIP_GUIDELLM` is unset. For a full customer-style benchmark (rates, duration, reports), use the top-level README — **[Load testing](../README.md#load-testing)** (`make guidellm-quadlet`).

## CI

GitHub Actions does **not** run `quadlet-e2e` (no RHAII CPU runner). Run on your RHEL/EC2 evaluation host.

## Adding a scenario

1. Add `scripts/quadlet-e2e-scenario-<name>.sh` (source `quadlet-lib.sh` + `quadlet-e2e-lib.sh`).
2. Document `<name>` in the table above.
3. Call `quadlet_e2e_scenario_teardown` at the end so the next scenario starts clean.
4. Register in `QUADLET_E2E_SCENARIOS` examples.

## Related Make targets

| Target | Role |
|--------|------|
| `make quadlet-setup` | Dirs, units, samples |
| `make quadlet-up` | Ordered production start |
| `make quadlet-verify` | Quick health + ticket models |
| `make quadlet-relaunch` | Reset + deploy (`QUADLET_RESET_CONFIRM=1`) |
