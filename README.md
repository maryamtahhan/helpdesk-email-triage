# Triage support email with tokenized PII on RHEL

Ingest customer support email, classify topic and urgency, and replace PII with reversible tokens — on a laptop, a single RHEL host, or OpenShift — using Red Hat AI Inference on CPU (or a built-in mock).

**Authors:** Michael Dawson ([midawson@redhat.com](mailto:midawson@redhat.com)) · Maryam Tahhan ([mtahhan@redhat.com](mailto:mtahhan@redhat.com)) · Anton Ivanov ([anivanov@redhat.com](mailto:anivanov@redhat.com))

## Table of Contents

- [At a glance](#at-a-glance)
- [What you'll see](#what-youll-see)
- [Architecture](#architecture)
- [Requirements](#requirements)
- [Deploy — pick a path](#deploy--pick-a-path)
- [Verify](#verify)
- [Configure](#configure)
- [Use the gateway](#use-the-gateway)
- [Agent inbox (demo UI)](#agent-inbox-demo-ui)
- [Integrate with your systems](#integrate-with-your-systems)
- [Commands and scripts](#commands-and-scripts)
- [CI/CD and customer pipelines](#cicd-and-customer-pipelines)
- [Repository structure](#repository-structure)
- [Technical details](#technical-details)
- [References](#references)

---

## At a glance

| | |
|---|---|
| **Problem** | Support mail mixes billing, access, and tech issues with card numbers, phones, and names. Downstream tools and logs should not see raw PII. |
| **Solution** | An **email gateway** regex-tokenizes structured PII into a local vault, sends **tokenized text only** to inference for category/urgency/summary, and exposes a safe **`TriageResult` JSON** API. Agents rehydrate PII from the vault by ticket ID. |
| **Reusable core** | `email-gateway/` — deploy without Streamlit; wire your own queue, CRM, or webhook consumer. |
| **Demo UI** | `agent-dashboard/` — Streamlit inbox (optional; not required for production). |
| **Inference** | Red Hat AI Inference 3.5 on CPU (production) or `inference-mock/` (laptop / CI). |

### Deployment paths

Pick **one** path — they share the same containers, env vars, and API contract.

| Path | Best for | What runs | Entry point |
|---|---|---|---|
| **Demo stack** | Laptop walkthrough, UI + tokenization | Mock inference + gateway + Streamlit | `make demo` or `compose.mock.demo.yml` |
| **Production RHEL** | On-prem CPU inference with RHAII | RHAII + gateway + Streamlit | `compose.yml` |
| **Gateway only** | ServiceNow, Salesforce, custom queue | Inference + gateway (no UI) | `make gateway-only` or `compose.gateway-only.yml` |
| **OpenShift** | Cluster deploy, customer GitOps | Kustomize overlays (mock, gateway-only, external RHAII) | `deploy/openshift/overlays/*` |
| **Quadlet** | Single RHEL host, systemd | Podman user units | `deploy/quadlet/` |
| **No containers** | Quick local hack | Native Python | `scripts/run-demo-local.sh` |
| **Kind / CI** | GitHub Actions Kubernetes test | Mock stack on kind | `make run-on-kind` / `make kind-e2e` |
| **Your CI pipeline** | Fork + your registry | Same Containerfiles, your namespace | [docs/customer-ci.md](docs/customer-ci.md) |

### Ports and endpoints (defaults)

| Service | Port | Purpose |
|---|---|---|
| Email gateway (HTTP) | **8080** | `GET /health`, `GET /tickets`, `POST /ingest`, `POST /ingest/raw` |
| Email gateway (SMTP) | **3025** | Accept RFC-822 mail (returns `250`, classifies in background) |
| Inference (mock or RHAII) | **8000** | OpenAI-compatible `/v1` API |
| Agent dashboard | **8501** | Streamlit demo inbox |

Vault rehydration (authorized agents only): `GET /tickets/{id}/vault` with header `X-Vault-Secret: <VAULT_SECRET>`.

### Published container images

Built by GitHub Actions and pushed to Quay (RHAII stays on `registry.redhat.io`):

| Image | Purpose |
|---|---|
| `quay.io/mtahhan/helpdesk-email-gateway` | SMTP/HTTP gateway, tokenization, ticket API |
| `quay.io/mtahhan/helpdesk-triage-ui` | Streamlit demo inbox |
| `quay.io/mtahhan/helpdesk-inference-mock` | OpenAI-compatible mock for laptops and CI |

Override in Compose with `GATEWAY_IMAGE`, `UI_IMAGE`, `MOCK_IMAGE`, or in OpenShift overlays via Kustomize `images:`.

---

## What you'll see

The demo is designed to be self-explanatory once the stack is running — no command-line steps required for the main walkthrough.

**Agent inbox** ([http://127.0.0.1:8501](http://127.0.0.1:8501) when using Compose):

- **Seven quick demo scenarios** in the sidebar (billing double-charge, MFA lockout, VPN failure, healthcare bill, HR payroll, GDPR erasure, thank-you note) — each triages instantly and adds a ticket to the queue.
- **Category filter** — `Billing`, `Tech Support`, `Account Access`, `General`.
- **Ticket detail** — AI-generated **category**, **urgency**, **X-Classification-Time** SLA tag, and **sanitized body** with tokens (`[NAME_1]`, `[CARD_LAST4_1]`, `[PHONE_1]`) instead of raw values.
- **📤 What downstream systems see** — live preview of the public `TriageResult` JSON (same payload a webhook would push).
- **🔓 View original PII vault** — authorized rehydration of original body + token map (requires `VAULT_SECRET`).
- **Reply helpers** — open mail client / copy sender after vault is open.

**Automatic ingest:** Sample `.eml` files in `sample_emails/` are picked up by the file watcher on start. The queue refreshes every 10 seconds.

Category, urgency, and sanitized text are **AI-generated** — verify before routing real tickets.

---

## Architecture

![Four-stage pipeline: email ingestion → email gateway regex-tokenizes PII into a local vault → Red Hat AI Inference 3.5 on CPU classifies category and urgency on pre-sanitized text → Streamlit agent inbox](docs/images/architecture-overview.svg)

| Stage | Component | What it does |
|---|---|---|
| 1 — Ingestion | SMTP listener / file watcher / HTTP | Accepts RFC-822 email from a mailbox, `.eml` drop, or REST |
| 2 — Email gateway | `email-gateway` | Regex-tokenizes PII (cards, phones, SSNs, emails, account IDs) into a vault keyed by ticket ID |
| 3 — Inference | RHAII or mock | Receives **tokenized text only**; returns category, urgency, residual name redaction, summary |
| 4 — Agent inbox | Streamlit (optional) | Tokenized queues; ticket ID links back to vault / CRM record |

**Agent workflow:** The sanitized body intentionally omits identifying details for untrusted channels. The agent reads the sender from the ticket envelope (stored in the vault), not from sanitized text. In enterprise deployments, the ticket ID maps to a CRM record (Salesforce, ServiceNow, etc.).

**Security split:** Regex handles structured PII (deterministic, auditable); inference handles category, urgency, summary, and residual names. Raw card numbers and SSNs never reach the model. See [Technical details](#technical-details).

---

## Requirements

### Hardware

| Profile | CPU | Memory | Storage | Notes |
|---|---|---|---|---|
| Demo (mock) | 2 vCPU | 4 GiB | 2 GiB | Laptop or RHEL; x86_64 or aarch64 |
| Gateway + UI | 1 vCPU | 1 GiB | — | Application only |
| RHAII + `Qwen2.5-1.5B` | 8 vCPU | 16 GiB (32 GiB rec.) | 20 GiB cache | x86_64 only |
| RHAII + `Qwen2.5-7B` | 16+ vCPU | 32+ GiB | — | Set `VLLM_CPU_KVCACHE_SPACE=10` |

For high throughput or large models, use GPU-backed Red Hat AI Inference instead of CPU.

### Software

- **RHEL path:** RHEL 9.4+, Podman 4.9+ with Compose, `registry.redhat.io` login, Hugging Face token
- **Demo path:** Podman or Docker Compose — mock replaces RHAII; no `registry.redhat.io` needed
- **OpenShift:** 4.x + `kustomize` / `oc`; see [docs/deploy-openshift.md](docs/deploy-openshift.md)
- **Local Python demo:** Python 3.11+ only

Rootless Podman is sufficient. Bind ports 8000, 3025, 8080, 8501 (or use OpenShift Routes).

---

## Deploy — pick a path

All paths use the same gateway API. Copy env defaults once: `cp .env.example .env`.

### Demo stack (mock inference + gateway + UI)

```bash
make demo
# equivalent: podman compose -f compose.mock.demo.yml up --build
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). No Hugging Face token or Red Hat registry required.

**Without Podman:** `./scripts/run-demo-local.sh`

#### Verify (Compose demo)

```bash
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool | head -20
```

Open: [http://127.0.0.1:8501](http://127.0.0.1:8501)

### Production RHEL (Red Hat AI Inference 3.5 + gateway + UI)

```bash
podman login registry.redhat.io
export HF_TOKEN="your_huggingface_token"
export RHEL_CACHE_DIR="$HOME/rhaii-cache"
mkdir -p "$RHEL_CACHE_DIR"
podman compose -f compose.yml up --build -d
```

First start downloads model weights (several minutes). Larger model:

```bash
MODEL_NAME=Qwen/Qwen2.5-7B-Instruct VLLM_CPU_KVCACHE_SPACE=10 \
  podman compose -f compose.yml up --build -d
```

### Gateway only (integrator — no Streamlit)

```bash
make gateway-only
# equivalent: podman compose -f compose.gateway-only.yml up --build
```

Wire your consumer to `:8080` (HTTP) and `:3025` (SMTP). CI runs `make compose-e2e` against **`compose.gateway-only.yml`** (mock inference), not `compose.yml` (real RHAII).

#### Verify (gateway only)

```bash
curl -sS http://127.0.0.1:8080/health
./scripts/ingest-sample.sh
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool | head -20
```

### OpenShift / Kubernetes

| Overlay | Use when |
|---|---|
| `deploy/openshift/overlays/helpdesk-email-triage` | **Recommended** — deploy into an existing project (`oc new-project`) |
| `deploy/openshift/overlays/mock-demo` | Greenfield — Kustomize creates the Namespace resource |
| `deploy/openshift/overlays/gateway-only` | API/SMTP only; no UI |
| `deploy/openshift/overlays/external-inference` | Gateway pointed at existing RHAII / vLLM Service |

```bash
oc new-project helpdesk-email-triage   # once
oc label namespace helpdesk-email-triage opendatahub.io/dashboard=true   # optional
make deploy-openshift
```

Route hostnames, gateway CORS, and Streamlit WebSocket settings are discovered automatically at pod startup — no manual patching.

Details: [deploy/openshift/README.md](deploy/openshift/README.md) · [docs/deploy-openshift.md](docs/deploy-openshift.md)

### RHEL systemd (Quadlet)

Single-host enterprise deploy without Compose: copy units from `deploy/quadlet/` to `~/.config/containers/systemd/`. See [deploy/quadlet/README.md](deploy/quadlet/README.md).

### Tear down

```bash
make down
# or individually:
podman compose -f compose.yml down -v
podman compose -f compose.mock.demo.yml down -v
podman compose -f compose.gateway-only.yml down -v
```

OpenShift: `DELETE_NAMESPACE=1 make undeploy-openshift` or `oc delete project helpdesk-email-triage`

---

## Verify

### OpenShift (`helpdesk-email-triage`)

After `make deploy-openshift`, confirm pods and routes are up:

```bash
oc get pods,route -n helpdesk-email-triage
```

Check the gateway API and dashboard Route (example hostnames on `apps.alpha.modelarch.org`):

```bash
curl -sk https://email-gateway-helpdesk-email-triage.apps.alpha.modelarch.org/health
curl -skI https://agent-dashboard-helpdesk-email-triage.apps.alpha.modelarch.org | head -5
```

Open: [https://agent-dashboard-helpdesk-email-triage.apps.alpha.modelarch.org](https://agent-dashboard-helpdesk-email-triage.apps.alpha.modelarch.org)

For another namespace or cluster, resolve hosts dynamically:

```bash
NS=helpdesk-email-triage
GW=$(oc get route email-gateway -n "$NS" -o jsonpath='{.spec.host}')
UI=$(oc get route agent-dashboard -n "$NS" -o jsonpath='{.spec.host}')
curl -sk "https://${GW}/health"
curl -skI "https://${UI}" | head -5
echo "Dashboard: https://${UI}"
```

Optional ingest smoke test:

```bash
curl -sk -X POST "https://${GW}/ingest/raw" \
  -H "Content-Type: application/json" \
  -d '{"sender":"test@example.com","subject":"Verify deploy","body":"OpenShift smoke test."}'
curl -sk "https://${GW}/tickets" | python3 -m json.tool | head -20
```

### Compose / laptop demo

```bash
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool | head -20
```

Open: [http://127.0.0.1:8501](http://127.0.0.1:8501)

### Kind (`make run-on-kind`)

Deploy the mock stack on a local kind cluster:

```bash
make run-on-kind
```

Port-forward in separate terminals, then verify:

```bash
kubectl port-forward -n helpdesk-kind-test svc/email-gateway 8080:8080 3025:3025
kubectl port-forward -n helpdesk-kind-test svc/agent-dashboard 8501:8501

curl -sS http://127.0.0.1:8080/health
./scripts/ingest-sample.sh
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool | head -20
curl -sI http://127.0.0.1:8501 | head -5
```

Open: [http://127.0.0.1:8501](http://127.0.0.1:8501)

Teardown: `make destroy-kind`

CI uses `make kind-e2e` (deploy → verify → destroy automatically).

---

## Configure

Key environment variables (full list in `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `VLLM_BASE_URL` | `http://rhaii-cpu-engine:8000/v1` | OpenAI-compatible inference base URL |
| `MODEL_NAME` | `Qwen/Qwen2.5-1.5B-Instruct` (prod) / `mock-triage` (demo) | Model ID sent to inference |
| `GATEWAY_MODE` | `FILE_WATCHER` | `FILE_WATCHER` watches `EMAIL_INPUT_DIR`; use `SMTP_ONLY` on OpenShift gateway-only |
| `VAULT_SECRET` | `helpdesk-demo-secret` | **Change before production** — gates `/vault` and dashboard |
| `DASHBOARD_ORIGIN` | `http://localhost:8501` | CORS origin for browser UI |
| `TICKET_SINK` | (empty) | Push delivery: `webhook:https://…` or `log` |
| `TICKET_SINK_SECRET` | (empty) | HMAC signing for webhook payloads |
| `GATEWAY_IMAGE` / `UI_IMAGE` / `MOCK_IMAGE` | `quay.io/mtahhan/helpdesk-*` | Override published images |

---

## Use the gateway

Three ingest paths — all produce the same `TriageResult`. Full API: [docs/integration.md](docs/integration.md).

| Method | How |
|---|---|
| **HTTP (.eml)** | `POST /ingest` with multipart file — `./scripts/ingest-sample.sh` |
| **HTTP (JSON)** | `POST /ingest/raw` with `sender`, `subject`, `body` |
| **SMTP** | Deliver mail to port **3025** — gateway returns `250` immediately |
| **File drop** | Place `.eml` in `sample_emails/` when `GATEWAY_MODE=FILE_WATCHER` |

**Health check:** `GET http://127.0.0.1:8080/health` → `{"status":"ok"}`

**List tickets:** `GET http://127.0.0.1:8080/tickets`

**Example JSON ingest:**

```bash
curl -sS -X POST http://127.0.0.1:8080/ingest/raw \
  -H "Content-Type: application/json" \
  -d '{"sender":"demo@example.com","subject":"VPN down","body":"Cannot connect from home."}'
```

**Pull vs push:** Poll `GET /tickets` (default), or set `TICKET_SINK=webhook:https://…` for push delivery after each triage. Same JSON either way.

**Tests (no running stack required for unit tests):**

```bash
make test          # unit tests
make test-webhook  # webhook sink e2e
make compose-e2e   # full stack smoke test (gateway-only compose)
```

---

## Agent inbox (demo UI)

| Feature | What it shows |
|---|---|
| Category sidebar | Filter by Billing, Tech Support, Account Access, General |
| Ticket queue | Click a ticket for category, urgency, SLA tag, sanitized body |
| 📤 Downstream JSON | Exact public API payload (`TriageResult`) |
| 🔓 Vault | Original body + token map (requires correct `VAULT_SECRET`) |
| ✉️ Reply | Mail client shortcuts after vault is open |

**Sample expectations** (fictional PII in `sample_emails/`):

- `01-billing-double-charge.eml` → **Billing** / **High**
- Thank-you / feedback → **General** / **Low**
- Structured PII appears as tokens in sanitized text, never raw card or phone values

**Classification speed:** Each ticket includes `classification_ms`. Mock stack: sub-second. RHAII on CPU: typically hundreds of ms to a few seconds. If inference is down, keyword fallback still ingests mail on already-tokenized text.

---

## Integrate with your systems

The gateway in `email-gateway/` is the reusable product. Streamlit is optional.

### `TriageResult` — public JSON contract

Returned by every ingest path; exposed at `GET /tickets` and `GET /tickets/{id}`:

`id`, `sender`, `subject`, `category`, `urgency`, `summary`, `sanitized_text`, `token_count`, `classification_ms`, `model`, `source`, `created_at`

Defined in `email-gateway/app/triage_result.py`. **No vault fields** in the public API.

### Pull vs push

| | **Pull** (default) | **Push** (`TICKET_SINK`) |
|---|---|---|
| Delivery | Your system calls `GET /tickets` | Gateway `POST`s to your URL |
| Config | None | `TICKET_SINK=webhook:https://…` |
| UI preview | Dashboard **📤** panel shows pull contract | Sink is backend-only |

```bash
export TICKET_SINK=webhook:https://case-mgmt.example.com/api/triage
export TICKET_SINK_SECRET=your-hmac-secret   # optional; X-Ticket-Signature header
```

`make test-webhook` runs a self-contained push simulation (no Compose needed).

### Python library

```python
from app.pipeline import process_parsed_email  # PYTHONPATH=email-gateway
```

See [docs/integration.md](docs/integration.md) for SMTP relay patterns, OpenShift notes, and schema details.

---

## Commands and scripts

| Command / script | Purpose |
|---|---|
| `make demo` | Full mock stack (inference + gateway + UI) |
| `make gateway-only` | Inference + gateway only |
| `make down` | Stop all compose stacks |
| `make ingest` | POST sample `.eml` to running gateway |
| `make test` | Unit tests |
| `make test-webhook` | Webhook sink e2e (no compose) |
| `make deploy-openshift` | Apply overlay, wait for pods, print Route URLs |
| `make undeploy-openshift` | Remove deployed resources (`DELETE_NAMESPACE=1` deletes project) |
| `make run-on-kind` | Deploy mock stack on kind (keeps cluster running) |
| `make destroy-kind` | Delete the local kind cluster (`helpdesk-ci`) |
| `make kind-e2e` | Deploy on kind, smoke test, then destroy cluster |
| `make validate-manifests` | Validate OpenShift and Kind Kustomize overlays |
| `make compose-e2e` | Mock-stack smoke test: health → ticket (via file watcher or API) |
| `make build-images` | Build all three Containerfiles with Podman |
| `scripts/ingest-sample.sh` | Curl sample `.eml` to `POST /ingest` |
| `scripts/run-demo-local.sh` | Native Python demo |
| `scripts/webhook-receiver.py` | Local webhook listener for manual testing |

---

## CI/CD and customer pipelines

| Workflow | Trigger | What it does |
|---|---|---|
| [ci.yml](.github/workflows/ci.yml) | PR + push to `main` | Tests, Compose validation, Kustomize validation, container builds, compose e2e, **kind e2e** |
| [publish-quay.yml](.github/workflows/publish-quay.yml) | Push to `main` (image paths), release, manual | Build, smoke-test, and push to Quay |
| [reusable-build.yml](.github/workflows/reusable-build.yml) | `workflow_call` from customer repos | Reusable build/push for all three images |

**CI uses the mock inference stack only.** `compose-e2e` and `kind-e2e` exercise `inference-mock`, not `registry.redhat.io/rhaii/...`. Real RHAII needs a subscribed RHEL host, `registry.redhat.io` login, an HF token, and minutes of model load time — run that path manually with `compose.yml` on your own hardware, not in GitHub Actions.

**Publish secrets:** `REDHAT_REGISTRY_USERNAME`, `REDHAT_REGISTRY_PASSWORD` (Quay robot with write access to all three repos).

**Fork and adopt:** Point `IMAGE_NAMESPACE` and Kustomize `images:` at your registry, enable the included workflows or call `reusable-build.yml`. Full guide: [docs/customer-ci.md](docs/customer-ci.md).

**Local CI parity:**

```bash
make test && make validate-manifests && make compose-e2e
```

---

## Repository structure

```
.
├── compose.yml                 # RHAII + gateway + UI
├── compose.mock.demo.yml       # Mock + gateway + UI
├── compose.gateway-only.yml    # Mock + gateway (integrator)
├── deploy/
│   ├── openshift/              # Kustomize base + overlays (OpenShift)
│   ├── kind/                   # Kustomize overlays for kind / CI
│   └── quadlet/                # Podman systemd units (RHEL)
├── email-gateway/              # Reusable gateway (API, SMTP, tokenization)
├── agent-dashboard/            # Streamlit demo UI
├── inference-mock/             # OpenAI-compatible mock
├── sample_emails/              # Demo .eml files (fictional PII)
├── scripts/                    # Ingest, e2e, webhook testing
├── .github/workflows/          # CI, publish, reusable build
└── docs/
    ├── integration.md          # API and adoption guide
    ├── deploy-openshift.md     # Cluster runbook
    ├── customer-ci.md          # Pipeline adoption
    └── testing-locally.md      # Laptop demo without RHEL
```

---

## Technical details

Classification uses the vLLM email gateway in `email-gateway/gateways/email_classification_gateway.py` (adapted from [redhat-et/vllm-audio-demo](https://github.com/redhat-et/vllm-audio-demo)). It can also run standalone:

```bash
python email-gateway/gateways/email_classification_gateway.py \
  --config email-gateway/vllm-email-gw.json \
  --file sample_emails/01-billing-double-charge.eml
```

**Regex (structured PII):** Cards (Luhn-validated), NANP phones, emails, SSNs, display names, `ACC-*` IDs → vault tokens. Deterministic and auditable; raw values never sent to inference.

**RHAII (classification + residual names):** Category, urgency, `[NAME_N]` redaction, one-line summary using tokens only. Merge step verifies model output; falls back to regex-sanitized text if tokens are dropped or raw PII reappears.

**Fallback:** If inference is unavailable, keyword triage on tokenized text still stores a ticket.

Ticket IDs start at `TICKET-8921`. Sample mail uses fictional test values (Visa `4111-1111-1111-1111`, `+1-212-555-01xx`, `000-00-0000`). Do not treat model output as a complete redaction guarantee.

**Load testing:** [GuideLLM](https://github.com/vllm-project/guidellm) against `:8000/v1`; drive `POST /ingest/raw` or SMTP for end-to-end gateway throughput.

---

## References

- [Integrating the email gateway](docs/integration.md)
- [Deploy on OpenShift](docs/deploy-openshift.md)
- [Customer CI pipelines](docs/customer-ci.md)
- [Testing locally without RHEL](docs/testing-locally.md)
- [Red Hat AI Inference 3.5 — CPU inference](https://docs.redhat.com/en/documentation/red_hat_ai_inference/3.5/html/getting_started/about-cpu-inference_getting-started)
- [AI quickstart catalog](https://docs.redhat.com/en/learn/ai-quickstarts)
- [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)

---

## Tags

| Field | Value |
|---|---|
| **Title** | Triage support email with tokenized PII on RHEL |
| **Product** | Red Hat AI Inference |
| **Use case** | Helpdesk triage, data sanitization |
| **Industry** | Banking and securities |
