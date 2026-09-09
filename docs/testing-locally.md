# Running the demo locally

**Fastest path:** [README Try it now](../README.md#try-it-now-about-2-minutes) — `make demo`, open port 8501, done.

**Hands-on walkthrough:** [README Quickstart walkthrough](../README.md#quickstart-walkthrough) — submit tickets, review classification/redaction, classification speed, quality checks, and optional GuideLLM load testing.

This guide walks through every feature in the demo UI and alternative run methods. No Red Hat subscription, registry login, GPU, or Hugging Face token required.

## Prerequisites

- Podman 4.9+ with Compose (`podman compose`), **or** Docker with `docker compose`
- Git

## Start the stack

```bash
git clone <repo-url>
cd helpdesk-email-triage
make demo
# or: podman compose -f compose.mock.demo.yml up --build
```

Mock compose uses service name `inference-mock` (real RHAII in `compose.yml` uses `rhaii-cpu-engine`).

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). Tickets from `sample_emails/` load automatically.

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

**Laptop** — benchmark the mock inference container directly (see [README Quickstart walkthrough — Load testing](../README.md#load-testing)).

**OpenShift** — after `make verify-openshift`:

```bash
make guidellm-openshift
```

Results land in `./results/guidellm-openshift/`. See [deploy-openshift.md](deploy-openshift.md#load-test-inference-guidellm).

## OpenShift

Cluster deploy is documented in the [README](../README.md#openshift-quick-deploy) (step-by-step) and [deploy-openshift.md](deploy-openshift.md) (overlay catalog). After verify, continue with the [Quickstart walkthrough](../README.md#quickstart-walkthrough).

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
