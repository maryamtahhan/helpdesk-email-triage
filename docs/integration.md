# Integrating the email gateway

The **email gateway** is the reusable building block in this quickstart. It ingests RFC-822 mail, regex-tokenizes structured PII into a local vault, calls Red Hat AI Inference (or a mock) for category, urgency, summary, and residual name redaction, and exposes sanitized tickets over HTTP and SMTP.

The Streamlit dashboard (`agent-dashboard/`) is a **demo inbox** only. Production adopters typically poll the ticket API, receive push delivery via `TICKET_SINK` webhooks, or import `process_parsed_email()` directly.

## What's included

| Component | Path | Description |
|---|---|---|
| **TriageResult** | `email-gateway/app/triage_result.py` | Typed public JSON contract (no vault fields) |
| **Ticket store** | `email-gateway/app/store.py` | Persistence + `GET /tickets` API |
| **Webhook sink** | `email-gateway/app/sink.py` | `TICKET_SINK` env — push `TriageResult` after triage |
| **Pipeline** | `email-gateway/app/pipeline.py` | `process_parsed_email()` / `process_raw_email()` entry points |
| **Gateway-only compose** | `compose.gateway-only.yml` | Inference + gateway, no Streamlit |
| **Integration guide** | `docs/integration.md` | This document |
| **Webhook test scripts** | `scripts/webhook-receiver.py`, `scripts/test-webhook-sink.sh` | Local receiver + `make test-webhook` |

## Quick start (gateway only)

Run inference + gateway without the UI:

```bash
podman compose -f compose.gateway-only.yml up --build
```

On RHEL with Red Hat AI Inference, start only the backend services from the full stack:

```bash
export HF_TOKEN="your_huggingface_token"
podman login registry.redhat.io
podman compose -f compose.yml up --build rhaii-cpu-engine email-gateway
```

Confirm health and ingest a sample:

```bash
curl -sS http://127.0.0.1:8080/health
./scripts/ingest-sample.sh
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool
```

## Adoption paths

### 1. SMTP relay

Point your mail transfer agent or helpdesk forwarder at the gateway SMTP listener (default port **3025**).

```bash
# Example: swaks (if installed)
swaks --to support@localhost --server 127.0.0.1:3025 \
  --from customer@example.com --header "Subject: Billing question" \
  --body "Please refund card 4111-1111-1111-1111"
```

The gateway accepts the message asynchronously and returns `250 Message accepted`. Poll `GET /tickets` (or `GET /tickets/{id}`) for the sanitized result.

Set `SMTP_BIND=127.0.0.1` in production unless the listener sits behind a firewall or authenticated relay.

### 2. HTTP ingest

**Multipart upload** — post a `.eml` file:

```bash
curl -sS -X POST http://127.0.0.1:8080/ingest \
  -F "file=@sample_emails/01-billing-double-charge.eml;type=message/rfc822"
```

**JSON body** — for chat widgets, web forms, or test harnesses:

```bash
curl -sS -X POST http://127.0.0.1:8080/ingest/raw \
  -H "Content-Type: application/json" \
  -d '{
    "sender": "jane.doe@example.com",
    "subject": "Locked out of account",
    "body": "Hi, I cannot log in. My phone is +1-212-555-0199."
  }'
```

Both endpoints return a **`TriageResult`** — the same public ticket object as `GET /tickets/{id}`.

### 3. Python library

Import the pipeline from your own worker or batch job:

```python
from app.pipeline import process_parsed_email, process_raw_email

# Structured fields (no RFC-822 parsing)
ticket = process_parsed_email(
    sender="jane.doe@example.com",
    subject="Billing dispute",
    body="I was charged twice on card 4111-1111-1111-1111.",
    source="my-app",
)

# Raw RFC-822 bytes (same path as SMTP / file watcher)
ticket = process_raw_email(open("message.eml", "rb").read(), source="batch:001")
```

Run with `PYTHONPATH=email-gateway` or install `email-gateway/` as a package in your environment. The function returns the same public fields as `GET /tickets/{id}`.

## Pull vs push: what the sink actually does

Every triaged email produces one **`TriageResult`** — a public JSON object with category, urgency, summary, and tokenized text. No vault, no `original_text`, no raw PII.

Downstream systems can consume that payload in two ways:

| | **Pull** (default) | **Push** (`TICKET_SINK`) |
|---|---|---|
| **Mechanism** | `GET /tickets` or `GET /tickets/{id}` | Gateway `POST`s JSON to your webhook URL |
| **When** | When your consumer polls | Right after each ingest (async background thread) |
| **Configuration** | None | `TICKET_SINK=webhook:https://your-system/hook` |
| **Where you see it** | Your HTTP client; ingest response body | Your webhook handler; or gateway logs if `log` sink |
| **In the demo UI?** | Yes — expand **📤 What downstream systems see** on any ticket | **No** — the sink is backend-only and does not change the dashboard |

**The JSON is the same in both cases.** The dashboard panel exists so agents and builders can *inspect* the contract during the demo. The sink exists so production integrators can *receive* that contract automatically without polling.

```
  Ingest (SMTP / HTTP / .eml)
           │
           ▼
    ┌──────────────┐
    │ email-gateway │  tokenize → classify → store
    └──────────────┘
           │
           ├──► TriageResult stored  ──► GET /tickets/{id}     (pull)
           │
           └──► TICKET_SINK dispatch ──► POST your-webhook-url  (push)
```

### What each sink shows

| `TICKET_SINK` value | What appears |
|---|---|
| *(unset)* | Nothing extra — use pull (`GET /tickets`) |
| `log` | One `TriageResult` JSON line per ticket in **gateway container logs** |
| `webhook:https://…` | HTTP `POST` to your URL; body is the `TriageResult` JSON below |

Example payload (push and pull return the same shape):

```json
{
  "id": "TICKET-8921",
  "sender": "[NAME_1] <[EMAIL_1]>",
  "subject": "VPN drops every 10 minutes",
  "sanitized_text": "My VPN drops. Please call [NAME_1] at [PHONE_1].",
  "summary": "Customer reports frequent VPN disconnects.",
  "category": "Tech Support",
  "urgency": "High",
  "token_count": 3,
  "classification_ms": 42.5,
  "model": "mock-triage",
  "source": "smtp",
  "created_at": "2026-08-27T19:13:57+00:00"
}
```

Run `make test-webhook` to see this end-to-end: a local receiver stands in for your case-management system and prints the `POST` body the gateway would send.

## Webhook delivery (`TICKET_SINK`)

After each message is triaged and stored, the gateway can **push** the public `TriageResult` JSON to your case-management system or queue adapter.

Set on the `email-gateway` service:

```bash
export TICKET_SINK=webhook:https://case-mgmt.example.com/api/triage
export TICKET_SINK_SECRET=your-hmac-secret   # optional but recommended
```

Multiple sinks are comma-separated:

```bash
export TICKET_SINK=log,webhook:https://case-mgmt.example.com/api/triage
```

**Delivery behavior:**
- Runs in a background thread so SMTP/HTTP ingest is not blocked
- Retries failed webhook `POST`s three times with exponential backoff
- Tickets are always persisted to the local store (polling still works)

**Webhook request:**
- Method: `POST`
- Header: `Content-Type: application/json`
- Header: `X-Ticket-Signature: sha256=<hmac>` when `TICKET_SINK_SECRET` is set (HMAC-SHA256 over the raw JSON body)
- Body: `TriageResult` JSON (no vault, no `original_text`)

Verify signatures on your receiver:

```python
import hashlib, hmac

def verify(body: bytes, secret: str, header: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)
```

For local testing, set `TICKET_SINK_SYNC=1` so delivery runs inline (used in unit tests).

### Scripts

| Script | Purpose |
|---|---|
| `make test-webhook` | Self-contained check: receiver + one triaged ticket (no compose) |
| `make webhook-receiver` | Start the local receiver until Ctrl-C |
| `./scripts/webhook-receiver.py` | Standalone receiver — `--port`, `--secret`, `--once` flags |
| `./scripts/test-webhook-sink.sh` | Orchestrates receiver + in-process triage (called by `make test-webhook`) |
| `./scripts/demo-webhook-with-compose.sh` | Receiver + `compose.gateway-only.yml` with `TICKET_SINK` wired |

Quick self-test (no containers):

```bash
make test-webhook
```

Manual flow with the full gateway stack:

```bash
# Terminal 1
make webhook-receiver

# Terminal 2 — gateway in compose (macOS/Podman: host.containers.internal)
export TICKET_SINK=webhook:http://host.containers.internal:9999/hook
export TICKET_SINK_SECRET=demo-secret
make gateway-only

# Terminal 3
./scripts/ingest-sample.sh
```

Or use the bundled helper:

```bash
./scripts/demo-webhook-with-compose.sh
```

## Public ticket API (`TriageResult`)

These fields define the **`TriageResult`** contract — safe to forward to downstream queues, webhooks, analytics, or lower-trust tiers. They never include the original body or vault map.

| Field | Type | Description |
|---|---|---|
| `id` | string | Ticket ID (`TICKET-8921`, …) — CRM correlation key |
| `sender` | string | Tokenized `From` header (routing key, not raw PII) |
| `subject` | string | Tokenized subject line |
| `category` | string | `Billing`, `Tech Support`, `Account Access`, or `General` |
| `urgency` | string | `High`, `Medium`, or `Low` |
| `summary` | string | One-line AI summary using tokens only |
| `sanitized_text` | string | Body with `[NAME_N]`, `[PHONE_N]`, `[CARD_LAST4_N]`, … |
| `token_count` | integer | Number of vault entries for this ticket |
| `classification_ms` | number | End-to-end classification latency (ms) |
| `model` | string | Inference model ID, or `heuristic-fallback` |
| `source` | string | Ingest provenance (`smtp`, `file:…`, `upload:…`, …) |
| `created_at` | string | ISO-8601 UTC timestamp |

Example response from `GET /tickets/TICKET-8921`:

```json
{
  "id": "TICKET-8921",
  "sender": "[EMAIL_1]",
  "subject": "Double charge on [CARD_LAST4_1]",
  "category": "Billing",
  "urgency": "High",
  "summary": "Customer reports duplicate charge on [CARD_LAST4_1].",
  "sanitized_text": "Please refund the duplicate charge on my Visa ending [CARD_LAST4_1]...",
  "token_count": 4,
  "classification_ms": 842.3,
  "model": "mock-triage",
  "source": "file:01-billing-double-charge.eml:…",
  "created_at": "2026-08-27T18:30:00+00:00"
}
```

List all tickets: `GET /tickets`  
Single ticket: `GET /tickets/{id}`  
Health: `GET /health`

## Vault API (authorized agents only)

`GET /tickets/{id}/vault` returns the original body, token map, and `original_sender` for reply routing. When `VAULT_SECRET` is set, callers must send `X-Vault-Secret: <secret>`.

```json
{
  "id": "TICKET-8921",
  "original_text": "…full body with raw PII…",
  "original_sender": "Jane Doe <jane.doe@example.com>",
  "sender": "[EMAIL_1]",
  "vault": {
    "[EMAIL_1]": "jane.doe@example.com",
    "[CARD_LAST4_1]": "****-1111"
  }
}
```

Do not expose this endpoint to untrusted consumers. The demo Streamlit UI gates vault access behind an explicit agent action; mirror that pattern in your CRM or case-management tool.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `VLLM_BASE_URL` | — | OpenAI-compatible inference base URL |
| `MODEL_NAME` | `Qwen/Qwen2.5-1.5B-Instruct` | Model served by RHAII / mock |
| `VAULT_SECRET` | *(unset)* | Require `X-Vault-Secret` on vault requests |
| `SMTP_BIND` | `127.0.0.1` | SMTP listener bind address |
| `SMTP_PORT` | `3025` | SMTP listener port |
| `GATEWAY_MODE` | `FILE_WATCHER` | Set to `SMTP_ONLY` to disable `.eml` watcher |
| `EMAIL_INPUT_DIR` | `/app/input_emails` | Directory watched for `.eml` drops |
| `TICKET_DATA_DIR` | `/app/data` | JSON persistence for tickets |
| `TICKET_SINK` | *(unset)* | Comma-separated sinks: `log`, `webhook:https://…` |
| `TICKET_SINK_SECRET` | *(unset)* | HMAC secret for webhook `X-Ticket-Signature` |
| `TICKET_SINK_SYNC` | *(unset)* | Set to `1` for inline delivery (tests/debug) |
| `DASHBOARD_ORIGIN` | `http://localhost:8501` | CORS origin (only needed if a browser UI calls the API) |

## Compose files

| File | Services |
|---|---|
| `compose.mock.demo.yml` | Mock inference + gateway + Streamlit UI |
| `compose.gateway-only.yml` | Mock inference + gateway (no UI) |
| `compose.yml` | Red Hat AI Inference + gateway + Streamlit UI |

## Standalone mail filter

The vLLM email classification gateway can also run as a stdin/stdout mail filter (no HTTP server):

```bash
python email-gateway/gateways/email_classification_gateway.py \
  --config email-gateway/vllm-email-gw.json \
  --file sample_emails/01-billing-double-charge.eml
```

That path classifies and sanitizes a single message but does not maintain the ticket vault or REST API. Use it when you only need MIME → JSON classification inside an existing MTA pipeline.

## Next steps

- **Demo UI** — `podman compose -f compose.mock.demo.yml up --build` and open [http://127.0.0.1:8501](http://127.0.0.1:8501) to see the public JSON payload panel and agent vault workflow.
- **Quality testing** — see [Testing locally](testing-locally.md) and the README walkthrough sections on classification quality and load testing.
