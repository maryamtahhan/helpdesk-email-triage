# Helpdesk email triage with tokenized PII

Classify support email by **category** and **urgency** while keeping raw PII out of logs, models, and downstream tools. Structured data (cards, phones, SSNs, emails, account IDs) is swapped for reversible tokens in a local vault before anything reaches inference.

**Authors:** Maryam Tahhan · Anton Ivanov · Michael Dawson

## Table of Contents

- [Overview](#overview)
  - [Who is this for?](#who-is-this-for)
  - [What this quickstart provides](#what-this-quickstart-provides)
  - [What you'll build](#what-youll-build)
  - [Key patterns you'll learn](#key-patterns-youll-learn)
  - [Architecture](#architecture)
- [Requirements](#requirements)
  - [Minimum hardware](#minimum-hardware)
  - [Minimum software](#minimum-software)
  - [Permissions](#permissions)
- [Choose your track](#choose-your-track)
- [Track 1: Run locally](#track-1-run-locally)
- [Track 2: Deploy to OpenShift](#track-2-deploy-to-openshift)
- [Track 3: Run on RHEL with systemd (Quadlet)](#track-3-run-on-rhel-with-systemd-quadlet)
- [Beyond the demo UI](#beyond-the-demo-ui)
- [OpenShift hardened pilot](#openshift-hardened-pilot)
- [Gateway API summary](#gateway-api-summary)
- [Configuration](#configuration)
- [Documentation](#documentation)
- [Development](#development)
- [Repository structure](#repository-structure)
- [References](#references)
- [Tags](#tags)

## Overview

### Who is this for?

This quickstart is designed for:

- **AI engineers** learning privacy-preserving inference: tokenize structured PII, classify on sanitized text only, and rehydrate from a vault when authorized.
- **Solution architects** evaluating helpdesk triage on Red Hat OpenShift or RHEL who need a working pipeline, not a slide deck.
- **Platform engineers** deploying the email gateway and optional Streamlit inbox with mock inference (laptop/CI) or Red Hat AI Inference (RHAII) CPU on cluster or single host.
- **System integrators** wiring CRMs, queues, or webhooks to `GET /tickets` and `POST /ingest` without adopting the demo UI.

### What this quickstart provides

A complete **ingest → vault tokenization → classification → ticket API** stack with sample support mail, an agent inbox, and OpenShift Kustomize overlays. The gateway (`email-gateway/`) is the reusable product; Streamlit is optional.

### What you'll build

By the end of the tracks below, you will have:

- An email gateway that ingests HTTP, SMTP (demo), or file-watched `.eml` drops
- Regex tokenization with a per-ticket PII vault (`[EMAIL_1]`, `[CARD_LAST4_1]`, `[ACCOUNT_ID_1]`, …)
- Category and urgency labels from mock inference (Track 1) or RHAII 3.5 CPU (Tracks 2–3 when configured)
- An optional Streamlit inbox with queue filters, vault rehydration, and downstream JSON preview
- Understanding of how to harden ingest auth and deploy on OpenShift or systemd-managed RHEL

### Key patterns you'll learn

| Pattern | What you'll see |
|---|---|
| **Structured PII tokenization** | Deterministic regex replaces cards, phones, SSNs, emails, `ACC-…` ids before model input |
| **Vault rehydration** | Original values keyed by ticket ID; gated by `VAULT_SECRET` |
| **Sanitized classification** | Inference sees tokenized body and subject only |
| **TriageResult contract** | Public ticket JSON excludes `original_text` and vault maps |
| **Multi-path ingest** | File watcher, JSON API, `.eml` upload, SMTP, sidebar scenarios |
| **Heuristic fallback** | Gateway still creates tickets if inference is down |
| **OpenShift overlays** | Mock vs RHAII CPU, optional hardened NetworkPolicies and API keys |

### Architecture

![Four-stage pipeline: ingestion → gateway vault → inference → optional agent inbox](docs/images/architecture-overview.svg)

1. **Ingest** — HTTP `:8080`, SMTP `:3025` (demo), or file watcher on `.eml` drops.
2. **Gateway** — Tokenizes structured PII into a vault; exposes `TriageResult` JSON and `/health/ready`.
3. **Inference** — RHAII 3.5 CPU (production) or built-in mock (laptop demo / CI). **Tokenized text only.**
4. **Agent inbox** *(optional)* — Streamlit on `:8501` (`/welcome` onboarding + inbox). Integrators can skip this.

**Privacy guarantee:** Raw card numbers, phones, and names do not reach the model. Downstream systems get tokens; authorized agents rehydrate locally.

## Requirements

### Minimum hardware

- **Track 1 (local):** 2 CPU cores, 4 GiB memory, Podman or Docker
- **Track 2 (OpenShift, mock):** Cluster with routes; modest worker nodes
- **Track 2 (OpenShift, RHAII CPU):** Workers with **x86_64 + AVX2**, **16 GiB+ allocatable RAM** per inference node (32 GiB recommended); model cache PVC
- **Track 3 (Quadlet / RHEL):** Same as RHAII CPU on a single host; 16 GiB+ RAM recommended

### Minimum software

- **Track 1:** `podman` or `docker` with Compose, `make`, `curl`, `python3`
- **Track 2:** `oc` CLI, OpenShift 4.x, `podman login registry.redhat.io` when using RHAII
- **Track 3:** RHEL 9.4+, rootless Podman, user systemd, Hugging Face token for RHAII

### Permissions

- **Track 1:** Local user only
- **Track 2:** Namespace admin (or equivalent) to create Routes, Deployments, Secrets
- **Track 3:** User systemd (`systemctl --user`); `podman login registry.redhat.io`

## Choose your track

| | Track 1: Local | Track 2: OpenShift | Track 3: RHEL Quadlet |
|---|---|---|---|
| **Goal** | Learn the pipeline in minutes | Deploy like a customer cluster | Production-style single host |
| **Time** | ~15 minutes | ~30 minutes (+ model download) | ~45 minutes (+ model download) |
| **Inference** | Mock (no registry) | Mock or RHAII CPU | RHAII CPU |
| **Start command** | `make demo` | `make deploy-openshift` | `systemctl --user enable --now …` |
| **UI** | `http://127.0.0.1:8501/welcome` | Dashboard Route `/welcome` | `http://127.0.0.1:8501/welcome` |

Start with **Track 1**. Use **Track 2** for OpenShift validation. Use **Track 3** when you need systemd lifecycle on RHEL instead of Compose.

---

## Track 1: Run locally

*~15 minutes. Mock inference — no GPU, Hugging Face token, or Red Hat registry.*

### Prerequisites

- `podman` or `docker` with Compose support
- `git`, `make`, `curl`, `python3`

### Step 1: Start the stack

```bash
git clone <repo-url> && cd helpdesk-email-triage
make demo
```

This builds and runs mock inference, the email gateway, and the agent dashboard (nginx on `:8501`, gateway on `:8080`, SMTP on `:3025`).

You should see containers become healthy and sample mail from `sample_emails/` ingested automatically.

Optional terminal check:

```bash
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool | head -10
```

**What's happening:** The file watcher reads `.eml` files from `sample_emails/`, the gateway tokenizes PII, calls the mock classifier, and stores tickets on disk.

### Step 2: Open the welcome page and inbox

1. Open **[http://127.0.0.1:8501/welcome](http://127.0.0.1:8501/welcome)** — onboarding, live pipeline diagram, before/after redaction example. The pill should show **local mock**.
2. Click **Open the inbox** (or go to `/`).
3. Confirm sample tickets appear in the left **Queue** column.

### Step 3: Submit support tickets

Try at least two ingest paths:

| Method | How |
|---|---|
| **Sidebar scenarios** | Click a **Quick demo scenario** (billing, MFA, VPN, …) |
| **Custom message** | Sidebar form → **Triage →** |
| **HTTP API** | See curl below |
| **SMTP** | Sidebar **↪** buttons, or send to `support@helpdesk.local` on port **3025** |

```bash
curl -sS -X POST http://127.0.0.1:8080/ingest/raw \
  -H "Content-Type: application/json" \
  -d '{"sender":"you@example.com","subject":"VPN issue","body":"Cannot connect from home office."}'
```

**What to look for:** New tickets in the queue within a few seconds.

### Step 4: Review classification by category

1. Set **Queue** to each category: `Billing`, `Tech Support`, `Account Access`, `General`, then `All`.
2. Set **Urgency** to `High` — urgent samples (double charge, MFA lockout) should surface.
3. Open tickets and confirm **category**, **urgency**, and subject in the detail pane.
4. Expand **Category breakdown** above the queue.

Expected results for file-watcher samples:

| Email | Category | Urgency |
|---|---|---|
| Double charge on card | Billing | High |
| MFA lockout | Account Access | High |
| VPN dropping | Tech Support | Medium |
| GDPR erasure request | General | Low |

### Step 5: Check redaction and the vault

1. Open the **billing / double charge** ticket.
2. In **Sanitized body**, confirm tokens such as `[NAME_1]`, `[EMAIL_1]`, `[CARD_LAST4_1]`, `[PHONE_1]`, `[ACCOUNT_ID_1]` — not raw values. **From** should be tokenized (e.g. `[EMAIL_1]`).
3. Click **View original PII vault** — compare the map to the original (demo secret: `helpdesk-demo-secret`).
4. Expand **What downstream systems see** — no `original_text` or vault in that JSON.

### Step 6: Review classification speed

1. Note **classification time** on each ticket in the queue (e.g. `42 ms classification`).
2. Check **Avg classification** in the metrics row at the top.

On mock inference, expect tens of milliseconds per ticket.

### Step 7: Test quality (optional)

1. Submit a custom message with a card number, phone, email, and `ACC-12345` — distinct tokens in body and vault.
2. Stop mock inference: `podman stop helpdesk-inference-mock` — ingest still works; `model` shows `heuristic-fallback`. Restart with `make demo` if needed.

### What you learned

1. **Multi-path ingest** into one ticket store
2. **Vault tokenization** before inference
3. **Classification** on sanitized text only
4. **Agent inbox** filters and vault rehydration
5. **Public ticket JSON** safe for webhooks and CRMs

Stop the stack:

```bash
make down
```

---

## Track 2: Deploy to OpenShift

*~30 minutes. Routes, optional RHAII CPU, same hands-on validation as Track 1.*

### Prerequisites

- `oc` logged into your cluster
- For **RHAII CPU:** `export HF_TOKEN="…"`, `podman login registry.redhat.io`
- Completed Track 1 recommended (same UI steps, different URLs)

### Step 1: Choose mock or RHAII

| Goal | Command |
|---|---|
| Auto (RHAII if creds exist, else mock) | `make deploy-openshift` |
| Mock only | `INFERENCE=mock make deploy-openshift` |
| RHAII CPU | `INFERENCE=rhaii make deploy-openshift` |

```bash
oc new-project helpdesk-email-triage    # once
export HF_TOKEN="your_huggingface_token"   # optional for mock
podman login registry.redhat.io            # optional for mock
make deploy-openshift
```

First RHAII start can take several minutes while weights download to the `rhaii-model-cache` PVC. Increase wait: `RHAII_WAIT_TIMEOUT=1200s make deploy-openshift`.

### Step 2: Verify deployment

```bash
make verify-openshift
```

You should see **Gateway** and **Dashboard** Route URLs, gateway `/health` JSON, dashboard HTTP headers, and at least one ticket (file watcher or verify ingest).

Save the dashboard host for the next steps: `https://<dashboard-route>/welcome`.

If the gateway Route is OAuth-protected (hardened overlay), verify uses in-cluster port-forward for API smoke tests — follow the script output.

### Step 3: Explore the UI on the cluster

Repeat **Track 1 Steps 2–6** on the dashboard Route:

- `/welcome` — pill shows **mock** or **RHAII** for this deploy
- Submit scenarios, filter queue/urgency, verify redaction and vault
- Use your cluster **vault secret** from `helpdesk-secrets` (not necessarily `helpdesk-demo-secret`)

### Step 4: Ingest from outside the pod

Use the **gateway Route URL** from verify (not `127.0.0.1:8080`):

```bash
GW="https://<gateway-route-host>"
curl -sk -X POST "${GW}/ingest/raw" \
  -H "Content-Type: application/json" \
  -d '{"sender":"you@example.com","subject":"OpenShift test","body":"Charged twice on card ACC-998877."}'
```

When `INGEST_API_KEY` is set (hardened overlay), add `-H "X-Ingest-Key: …"` from `oc get secret helpdesk-secrets …`.

### Step 5: Load test inference (RHAII only)

Skip on mock-only deploys.

```bash
make guidellm-openshift
```

Results land in `./results/guidellm-openshift/`. See [docs/deploy-openshift.md](docs/deploy-openshift.md#load-test-inference-guidellm) for tuning.

### What you get on OpenShift

- **Routes** for gateway and dashboard with CORS/WebSocket discovery at pod startup
- **Kustomize overlays** for mock, RHAII CPU, and hardened pilots
- **Optional GuideLLM Job** against in-cluster inference Service DNS
- **NetworkPolicies and API keys** on hardened overlays

### Delete

```bash
make undeploy-openshift
# Remove the whole project:
DELETE_NAMESPACE=1 make undeploy-openshift
```

Full overlay catalog: [docs/deploy-openshift.md](docs/deploy-openshift.md).

---

## Track 3: Run on RHEL with systemd (Quadlet)

*~45 minutes. Real RHAII CPU on a single host, containers managed by user systemd.*

### Prerequisites

- RHEL 9.4+ with rootless Podman
- `podman login registry.redhat.io`
- Hugging Face token and a strong `VAULT_SECRET`
- Completed Track 1 recommended

### Step 1: Prepare secrets and sample mail

```bash
mkdir -p ~/.config/helpdesk ~/helpdesk/sample_emails ~/rhaii-cache
cat > ~/.config/helpdesk/secrets.env <<'EOF'
HUGGING_FACE_HUB_TOKEN=hf_your_token_here
VAULT_SECRET=change-me-before-deploy
EOF
chmod 600 ~/.config/helpdesk/secrets.env

cp -r sample_emails/. ~/helpdesk/sample_emails/
cp -r docs/. ~/helpdesk/docs/
```

### Step 2: Build images

From the repo root (gateway `Containerfile` expects repo context):

```bash
podman build -f email-gateway/Containerfile -t localhost/helpdesk-email-gateway:prod .
podman build -f agent-dashboard/Containerfile -t localhost/helpdesk-triage-ui:prod .
```

### Step 3: Install Quadlet units and start

```bash
cp deploy/quadlet/*.container deploy/quadlet/*.network deploy/quadlet/*.volume \
   ~/.config/containers/systemd/

systemctl --user daemon-reload
systemctl --user enable --now rhaii-cpu-engine.service email-gateway.service agent-dashboard.service
```

Watch RHAII come up (first start downloads weights):

```bash
journalctl --user -u rhaii-cpu-engine -f
```

### Step 4: Verify

```bash
systemctl --user status rhaii-cpu-engine email-gateway agent-dashboard
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/health/ready
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool | head -20
```

Open **[http://127.0.0.1:8501/welcome](http://127.0.0.1:8501/welcome)** — pill should reflect **RHAII**, not mock.

### Step 5: Hands-on validation

Repeat **Track 1 Steps 3–6**. Vault rehydration uses `VAULT_SECRET` from `secrets.env`.

Optional:

```bash
./scripts/ingest-sample.sh
```

### Stop

```bash
systemctl --user stop agent-dashboard email-gateway rhaii-cpu-engine
```

**Compose alternative** on RHEL (no systemd): see [Production RHEL with Compose](#production-rhel-with-compose) below. Full Quadlet notes: [deploy/quadlet/README.md](deploy/quadlet/README.md).

---

## Beyond the demo UI

### Integrators (gateway only)

```bash
make gateway-only
```

No Streamlit — mock inference + gateway only. Wire your queue via [docs/integration.md](docs/integration.md) (`POST /ingest`, webhooks, `TICKET_SINK`).

### Production RHEL with Compose

```bash
cp .env.example .env
podman login registry.redhat.io
export HF_TOKEN="your_huggingface_token"
export RHEL_CACHE_DIR="$HOME/rhaii-cache" && mkdir -p "$RHEL_CACHE_DIR"
podman compose -f compose.yml up --build -d
```

Open [http://127.0.0.1:8501/welcome](http://127.0.0.1:8501/welcome). Prefer Quadlet when you need boot integration and `journalctl` per service.

### Demo UI deep dive

Every sidebar control: [docs/testing-locally.md](docs/testing-locally.md).

---

## OpenShift hardened pilot

NetworkPolicies, OAuth on Routes, non-demo secrets:

```bash
export VAULT_SECRET="$(openssl rand -hex 32)"
export INGEST_API_KEY="$(openssl rand -hex 16)"
oc create secret generic helpdesk-secrets \
  --from-literal=VAULT_SECRET="$VAULT_SECRET" \
  --from-literal=INGEST_API_KEY="$INGEST_API_KEY" \
  -n helpdesk-email-triage --dry-run=client -o yaml | oc apply -f -

# Mock + hardening:
OVERLAY=deploy/openshift/overlays/hardened make deploy-openshift

# RHAII CPU + hardening (HF_TOKEN + registry login):
INFERENCE=rhaii OVERLAY=deploy/openshift/overlays/hardened make deploy-openshift
```

> `OVERLAY=.../hardened` alone deploys **mock** inference. Add `INFERENCE=rhaii` for RHAII CPU.

HTTP ingest then requires `X-Ingest-Key`. Pin images: `IMAGE_TAG=v1.2.3 make deploy-openshift`.

---

## Gateway API summary

The reusable product is `email-gateway/` — Streamlit is optional.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness |
| `GET /health/ready` | Readiness (inference reachable) |
| `POST /ingest` | Upload `.eml` |
| `POST /ingest/raw` | JSON `{sender, subject, body}` |
| `GET /tickets` | List tickets (`X-Ingest-Key` when configured) |
| `GET /tickets/{id}` | Single ticket |
| `GET /tickets/{id}/vault` | Rehydrate PII — `X-Vault-Secret` or `X-Ingest-Key` |

**Ports:** HTTP `8080` · SMTP `3025` · inference `8000` · dashboard `8501`

Full reference: [docs/integration.md](docs/integration.md)

---

## Configuration

Copy defaults: `cp .env.example .env`

| Variable | What it does |
|---|---|
| `VAULT_SECRET` | Gates vault rehydration |
| `INGEST_API_KEY` | Requires `X-Ingest-Key` on ingest and ticket APIs when set |
| `MODEL_NAME` | `Qwen/Qwen2.5-1.5B-Instruct` (RHAII) or `mock-triage` (demo) |
| `HF_TOKEN` | Hugging Face token for RHAII |
| `INFERENCE` | OpenShift: `auto`, `mock`, or `rhaii` |
| `IMAGE_TAG` | Pin container tags on OpenShift deploy |
| `TICKET_SINK` | `webhook:https://…` or `log` |

See `.env.example` for the full list.

---

## Documentation

| Guide | When to read it |
|---|---|
| [docs/quickstart-walkthrough.md](docs/quickstart-walkthrough.md) | Extended walkthrough + GuideLLM command reference |
| [docs/testing-locally.md](docs/testing-locally.md) | Every demo UI feature |
| [docs/integration.md](docs/integration.md) | HTTP/SMTP API, auth, webhooks |
| [docs/deploy-openshift.md](docs/deploy-openshift.md) | Overlays, verify, production checklist |
| [docs/customer-ci.md](docs/customer-ci.md) | Fork, Quay publish, pipeline adoption |
| [deploy/openshift/README.md](deploy/openshift/README.md) | Kustomize layout |
| [deploy/quadlet/README.md](deploy/quadlet/README.md) | Quadlet units |

---

## Development

```bash
make test              # unit tests (no running stack)
make lint
make compose-e2e       # mock gateway stack smoke test
make validate-manifests
make test-openshift-overlay
make build-images
```

**CI** (on every PR): ruff, tests, compose e2e, kind e2e, container builds (mock inference only).

**Published images:** `quay.io/mtahhan/helpdesk-email-gateway`, `helpdesk-triage-ui`, `helpdesk-inference-mock`.

---

## Repository structure

```
.
├── email-gateway/          # API, SMTP, tokenization, vault
├── agent-dashboard/        # Streamlit inbox + welcome page
├── inference-mock/         # OpenAI-compatible mock for laptop/CI
├── sample_emails/          # Demo .eml (fictional PII)
├── compose*.yml            # Laptop / RHEL stacks
├── deploy/openshift/       # Kustomize overlays
├── deploy/quadlet/         # systemd Quadlet units
└── scripts/                # deploy, verify, ingest helpers
```

---

## References

- [Red Hat AI Inference 3.5 — CPU inference](https://docs.redhat.com/en/documentation/red_hat_ai_inference/3.5/html/getting_started/about-cpu-inference_getting-started)
- [AI quickstart catalog](https://docs.redhat.com/en/learn/ai-quickstarts)
- [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)
- [GuideLLM](https://github.com/vllm-project/guidellm)

---

## Tags

`helpdesk` `email` `triage` `pii` `tokenization` `red-hat-ai-inference` `openshift` `rhel` `streamlit` `quickstart`
