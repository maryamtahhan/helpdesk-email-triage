# Integrating the email gateway

The **email gateway** is the reusable building block in this quickstart. It ingests RFC-822 mail, regex-tokenizes structured PII into a local vault, calls Red Hat AI Inference (or a mock) for category, urgency, summary, and residual name redaction, and exposes sanitized tickets over HTTP and SMTP.

The Streamlit dashboard (`agent-dashboard/`) is a **demo inbox** only. Production adopters typically poll the ticket API, subscribe to a future webhook sink, or import `process_parsed_email()` directly.

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

Both endpoints return the **public** ticket object (see schema below).

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

## Public ticket API

These fields are safe to forward to downstream queues, analytics, or lower-trust tiers. They never include the original body or vault map.

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
- **Webhook sink** — not implemented in this release; poll `GET /tickets` or import the Python pipeline until a push-based sink is added.
