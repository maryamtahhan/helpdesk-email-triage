# Running the demo locally

**Fastest path:** [README Quick start](../README.md#quick-start-laptop-demo) — `make demo`, open port 8501, done.

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

## OpenShift

Cluster deploy is documented in the [README](../README.md#openshift--kubernetes) (step-by-step) and [deploy-openshift.md](deploy-openshift.md) (overlay catalog).

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
