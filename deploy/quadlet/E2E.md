# Quadlet maintainer E2E validation

Automated checks for **RHEL + rootless Podman + user systemd** — not for end-customer install docs.

## Requirements

- Same host prerequisites as [README.md](README.md) (`podman`, `make`, registry login, `secrets.env`, prod images built).
- **≥16 GiB RAM** and RHAII already cached or a valid `HUGGING_FACE_HUB_TOKEN`.
- Run from repo root as the user that owns the Quadlet units (`ec2-user`, etc.).

## Run all scenarios

```bash
make quadlet-build    # once, or QUADLET_E2E_BUILD=1 make quadlet-e2e
make quadlet-e2e
```

Default scenarios: **`full`**, then **`gateway-only`**. Each scenario stops services and clears `tickets.json` when finished.

### Scenarios

| Scenario | Stack | Checks |
|----------|--------|--------|
| `full` | inference + gateway + Streamlit | `/health/ready`, dashboard `/welcome`, `POST /ingest/raw`, file watcher on `~/helpdesk/sample_emails`, short **GuideLLM**, teardown |
| `gateway-only` | inference + gateway (no UI) | `:8501` not serving, gateway ready, HTTP ingest, `GET /tickets` |

### Useful environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `QUADLET_E2E_SCENARIOS` | `full,gateway-only` | Comma-separated scenario names |
| `QUADLET_E2E_SKIP_GUIDELLM` | `0` | Set to `1` to skip GuideLLM in `full` (faster) |
| `QUADLET_E2E_GUIDELLM_SECONDS` | `90` | Short benchmark duration |
| `QUADLET_E2E_GUIDELLM_RATE` | `1` | Single concurrent stream for stability |
| `QUADLET_E2E_BUILD` | `0` | Set to `1` to run `quadlet-build` first |
| `QUADLET_E2E_INITIAL_RESET` | `0` | Set to `1` for `quadlet-reset` + `quadlet-setup` before tests |
| `QUADLET_E2E_REQUIRE_MODEL` | `1` | Fail ingest if `model` is `heuristic-fallback` |
| `RHAII_WAIT_TIMEOUT` | `900` | Inference boot wait (inherited from quadlet-lib) |

Examples:

```bash
QUADLET_E2E_SKIP_GUIDELLM=1 make quadlet-e2e
QUADLET_E2E_SCENARIOS=gateway-only make quadlet-e2e
QUADLET_E2E_INITIAL_RESET=1 QUADLET_E2E_BUILD=1 make quadlet-e2e
```

## Reports

- JSON summary: `results/quadlet-e2e/report-<timestamp>.json` (per-step PASS/FAIL).
- GuideLLM artifacts (full scenario): `results/quadlet-e2e/full/guidellm/`.

Exit code **0** only if every scenario reports `pass`.

## CI note

GitHub Actions does **not** run this job (no RHAII CPU runner). Execute on your EC2/RHEL evaluation host after deploy changes.

## Adding a scenario

1. Add `scripts/quadlet-e2e-scenario-<name>.sh` (source `quadlet-lib.sh` + `quadlet-e2e-lib.sh`).
2. Register the name in `QUADLET_E2E_SCENARIOS` documentation above.
3. End with `quadlet_e2e_scenario_teardown` so the next scenario starts clean.
