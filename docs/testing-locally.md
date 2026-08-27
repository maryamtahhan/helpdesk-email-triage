# Running the demo locally (mock inference)

This guide lets you walk the full helpdesk-triage UI on a laptop without any Red Hat subscription, container registry login, GPU, or Hugging Face token. A lightweight mock server stands in for the AI inference engine and returns realistic structured responses instantly.

## Prerequisites

- Python 3.11 or later (`python3 --version`)
- Git

That's it. No Podman, no Docker, no cloud account.

## Quick start

```bash
git clone <repo-url>
cd helpdesk-email-triage

chmod +x scripts/run-demo-local.sh
./scripts/run-demo-local.sh
```

The script:
1. Creates a `.venv` and installs dependencies
2. Starts the mock inference server on port 8000
3. Starts the email gateway on port 8080
4. Ingests the sample `.eml` files from `sample_emails/`
5. Opens the Streamlit dashboard at [http://127.0.0.1:8501](http://127.0.0.1:8501) in your browser

Stop everything with **Ctrl-C**.

## What you'll see

When the dashboard opens, the queue on the left should already contain several tickets auto-ingested from `sample_emails/`. The **Model** field in the sidebar shows `mock-triage`.

| Sample email | Category | Urgency |
|---|---|---|
| Double charge on card | Billing | High |
| MFA lockout | Account Access | High |
| VPN dropping | Tech Support | High |
| GDPR erasure request | General | Low |
| Healthcare ER bill | Billing | High |
| HR payroll dispute | Billing | High |
| Thank-you note | General | Low |

## Things to try

### 1. Quick demo scenarios (sidebar)

Click any of the seven scenario buttons in the sidebar. Each injects a pre-built email through the full pipeline — regex tokenization, mock classification, ticket creation — and selects the new ticket in the queue.

### 2. Custom message

Fill in the **Custom message** form in the sidebar with any sender, subject, and body. Include a phone number, credit card, or name to see how the tokenizer replaces them with structured tokens (`[NAME_1]`, `[PHONE_1]`, `[CARD_LAST4_1]`, etc.).

### 3. SMTP ingest (alternative path)

The **SMTP ingest** section in the sidebar sends an email directly to the SMTP listener on port 3025, bypassing the HTTP API — the same path a real mail server would use. Click **↪ Double charge** or **↪ MFA lockout** to send an RFC-822 message over SMTP. The ticket appears in the queue within the next 10-second auto-refresh.

You can also send manually with any SMTP client or `swaks`:

```bash
swaks --to support@helpdesk.local \
      --from test@example.com \
      --server 127.0.0.1:3025 \
      --body "Hi, I'm Alex. Account ACC-12345 was charged twice on 4111-1111-1111-1111."
```

### 4. Drop a `.eml` file

Copy any RFC-822 `.eml` file into `sample_emails/`. The file watcher picks it up automatically within a few seconds and creates a ticket.

### 5. Authorized rehydration

Click a ticket, then click **🔓 View original PII vault**. The left panel shows the original body with raw PII highlighted in red; the right panel shows the sanitized version with blue tokens. The token map table below lists exactly which token maps to which original value. Click **🔒 Close vault** — the state resets independently for each ticket.

## Containerised mock stack (optional)

If you have Podman or Docker and prefer containers:

```bash
podman compose -f compose.mock.demo.yml up --build
# or
docker compose -f compose.mock.demo.yml up --build
```

Then open [http://127.0.0.1:8501](http://127.0.0.1:8501). Tear down with:

```bash
podman compose -f compose.mock.demo.yml down -v
```

## Differences from the production stack

| | Mock stack | Production (RHAIIS) |
|---|---|---|
| Inference | Deterministic mock — always returns plausible JSON | `Qwen/Qwen2.5-1.5B-Instruct` on CPU via Red Hat AI Inference 3.5 |
| Registry login | Not required | `podman login registry.redhat.io` |
| Hugging Face token | Not required | Required to download model weights |
| RHEL required | No — runs on macOS and Linux | RHEL 9.4+ x86_64 |
| Cold start | ~5 seconds | Several minutes (model download on first run) |
| Classification quality | Fixed responses | Real LLM — output varies |

The tokenization and vault logic, the API surface, and the entire dashboard are identical between the two stacks.
