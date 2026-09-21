# Running the demo locally

**Customer paths:** [README Track 1 (OpenShift RHAII)](../README.md#track-1-deploy-to-openshift-rhaii-cpu) or [Track 2 (Quadlet)](../README.md#track-2-run-on-rhel-with-systemd-quadlet). **Maintainers:** [local mock stack](../CONTRIBUTING.md#local-mock-validation) — `make demo`, open `/welcome`. **Automated test matrix:** [testing/README.md](testing/README.md).

**Hands-on walkthrough:** [quickstart-walkthrough.md](quickstart-walkthrough.md) — submit tickets, review classification/redaction, classification speed, quality checks, and optional GuideLLM load testing.

This guide walks through every feature in the demo UI and alternative run methods. No Red Hat subscription, registry login, GPU, or Hugging Face token required.

## Prerequisites

- Podman 4.9+ with Compose (`podman compose`), **or** Docker with `docker compose`. On **RHEL**, if `podman compose` is missing: `sudo dnf install -y git make python-pip`, then `pip3 install --user podman-compose` and ensure `~/.local/bin` is on `PATH`.
- Git (clone the repo; often installed with the `dnf` line above)

## Start the stack

```bash
git clone <repo-url>
cd helpdesk-email-triage
make demo
# or: podman compose -f compose.mock.demo.yml up --build
```

Mock compose uses service name `inference-mock` (real RHAII in `compose.yml` uses `rhaii-cpu-engine`).

Open [http://127.0.0.1:8501/welcome](http://127.0.0.1:8501/welcome) (inbox at `/inbox/`). Tickets from `sample_emails/` load automatically.

## Verify

```bash
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/health/ready
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool | head -20
./scripts/ingest-sample.sh    # optional
```

Stop: `make down` or `podman compose -f compose.mock.demo.yml down -v`

Gateway without UI: `make gateway-only` ([integration.md](integration.md)).

## What you'll see

Sidebar **Model** shows `mock-triage`. Queue auto-refreshes every 10 seconds.

| Sample email | Category | Urgency |
|---|---|---|
| Double charge on card | Billing | High |
| MFA lockout | Account Access | High |
| VPN dropping | Tech Support | Medium |
| GDPR erasure request | General | Low |
| Healthcare ER bill | Billing | High |
| HR payroll dispute | Billing | High |
| Thank-you note | General | Low |

## Things to try

1. **Quick demo scenarios** — sidebar buttons triage pre-built mail instantly.
2. **Custom message** — sidebar form; watch tokens like `[NAME_1]`, `[PHONE_1]` appear.
3. **SMTP ingest** — sidebar **↪** buttons or `swaks` to port 3025:

```bash
swaks --to support@helpdesk.local --from test@example.com \
      --server 127.0.0.1:3025 \
      --body "Account ACC-12345 charged twice on 4111-1111-1111-1111."
```

4. **Drop a `.eml` file** — copy into `sample_emails/`; file watcher ingests within seconds.
5. **Vault** — open a ticket → **🔓 View original PII vault** → compare token map vs raw body.

## Without containers

```bash
./scripts/run-demo-local.sh
```

Stop with Ctrl-C, or `podman compose -f compose.mock.demo.yml down` if processes linger.

## Load testing (GuideLLM)

**Laptop** — benchmark the mock inference container directly (see [quickstart-walkthrough — Load testing](quickstart-walkthrough.md#load-testing)).

**OpenShift** — after `make verify-openshift` on an **RHAII** deploy (`INFERENCE=rhaii` or rhaii-demo / hardened-rhaii overlay):

```bash
make guidellm-openshift
```

Results land in `./results/guidellm-openshift/`. See [deploy-openshift.md](deploy-openshift.md#load-test-inference-guidellm).

**RHEL Quadlet** — after inference responds on `:8000`:

```bash
make guidellm-quadlet
```

Results: `./results/guidellm-quadlet/`. Same `registry.redhat.io/rhai/guidellm-rhel9` image as OpenShift.

## OpenShift

Cluster deploy is documented in [README Track 1](../README.md#track-1-deploy-to-openshift-rhaii-cpu) and [deploy-openshift.md](deploy-openshift.md) (overlay catalog). After verify, continue with [Submit support tickets](../README.md#submit-support-tickets) through [What you've accomplished](../README.md#what-youve-accomplished), or [quickstart-walkthrough.md](quickstart-walkthrough.md).

## Mock vs RHAII

| | Mock (`make demo`) | RHAII (`compose.yml` or OpenShift `INFERENCE=rhaii`) |
|---|---|---|
| Inference | Deterministic mock | `Qwen/Qwen2.5-1.5B-Instruct` on CPU |
| Registry / HF token | Not required | Required |
| Cold start | ~5 seconds | Minutes (model download) |
| API and UI | Identical | Identical |

## Webhook test (no UI)

```bash
make test-webhook
```

Simulates push delivery (`TICKET_SINK`). Compare with pull: ticket detail → **📤 What downstream systems see**.
