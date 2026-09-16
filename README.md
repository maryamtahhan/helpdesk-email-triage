# Helpdesk email triage with tokenized PII

Classify support email by **category** and **urgency** while keeping raw PII out of logs, models, and downstream tools. Structured data (cards, phones, SSNs, emails, account IDs) is swapped for reversible tokens in a local vault before anything reaches inference.

**Customer evaluation** runs **Red Hat AI Inference (RHAII) 3.5 on CPU** — on OpenShift (Track 1) or a single RHEL host with systemd (Track 2). A **local mock stack** (Track 3) is for quick UI/CI checks without a cluster; it does not replace trying the real classifier.

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
- [Track 1: Deploy to OpenShift (RHAII CPU)](#track-1-deploy-to-openshift-rhaii-cpu)
- [Track 2: Run on RHEL with systemd (Quadlet)](#track-2-run-on-rhel-with-systemd-quadlet)
- [Hands-on validation](#hands-on-validation)
- [Benchmark inference with GuideLLM](#benchmark-inference-with-guidellm)
- [Track 3: Local mock validation (maintainers)](#track-3-local-mock-validation-maintainers)
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

**Platform engineers, AI engineers, and architects** who want to learn **CPU inference with [Red Hat AI Inference (RHAII) 3.5](https://docs.redhat.com/en/documentation/red_hat_ai_inference/3.5/html/getting_started/about-cpu-inference_getting-started)** on OpenShift or RHEL: pull and run an instruction-tuned model on **x86_64 + AVX512** (no GPU), wire an app to an OpenAI-compatible endpoint, observe readiness and latency, and optionally benchmark with GuideLLM.

The sample app is **helpdesk email triage** (ingest → tokenize PII → classify on sanitized text). That domain shows a realistic gateway in front of RHAII; integrators can use the API without the Streamlit inbox. **Track 3 (local mock)** is for UI/CI smoke tests only — it is not a substitute for trying RHAII.

### What this quickstart provides

A complete **ingest → vault tokenization → classification → ticket API** stack with sample support mail, an agent inbox, and OpenShift Kustomize overlays. The gateway (`email-gateway/`) is the reusable product; Streamlit is optional.

### What you'll build

By the end of the tracks below, you will have:

- An email gateway that ingests HTTP, SMTP (demo), or file-watched `.eml` drops
- Regex tokenization with a per-ticket PII vault (`[EMAIL_1]`, `[CARD_LAST4_1]`, `[ACCOUNT_ID_1]`, …)
- Category and urgency labels from **RHAII 3.5 CPU** (`Qwen/Qwen2.5-1.5B-Instruct` on tokenized text)
- An optional Streamlit inbox with queue filters, vault rehydration, and downstream JSON preview
- Optional GuideLLM benchmarking on OpenShift to size inference for a pilot
- Understanding of how to harden ingest auth on OpenShift overlays

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

![Four-stage pipeline: ingestion → gateway vault → inference → optional agent inbox](docs/images/architecture-overview.png)

1. **Ingest** — HTTP `:8080`, SMTP `:3025` (demo), or file watcher on `.eml` drops.
2. **Gateway** — Tokenizes structured PII into a vault; exposes `TriageResult` JSON and `/health/ready`.
3. **Inference** — **RHAII 3.5 CPU** (customer tracks) or built-in mock (Track 3 / CI only). **Tokenized text only.**
4. **Agent inbox** *(optional)* — Streamlit on `:8501` (`/welcome` onboarding + inbox). Integrators can skip this.

**Privacy guarantee:** Raw card numbers, phones, and names do not reach the model. Downstream systems get tokens; authorized agents rehydrate locally.

## Requirements

### RHAII CPU hardware (Tracks 1 and 2)

Plan for **real** inference, not the mock:

| | OpenShift (Track 1) | RHEL host (Track 2) |
|---|---|---|
| **CPU** | **x86_64 + AVX512** on inference worker(s) | **x86_64 + AVX512** |
| **Memory** | **16 GiB+ allocatable RAM** on the inference node (**32 GiB recommended**) | **16 GiB+ system RAM** (**32 GiB recommended**) |
| **Storage** | `rhaii-model-cache` PVC for downloaded weights | `~/rhaii-cache` (or path in Quadlet unit) |
| **Registry** | `podman login registry.redhat.io` | Same |
| **Model access** | Hugging Face token (`HF_TOKEN` / `hf-secret`) | `HUGGING_FACE_HUB_TOKEN` in `secrets.env` |

First start downloads **Qwen2.5-1.5B-Instruct** weights — allow **several minutes** (longer on slow networks). No GPU required.

### Minimum software

- **Track 1:** `oc` CLI, OpenShift 5.x, `make`, `podman login registry.redhat.io`, `HF_TOKEN`
- **Track 2:** RHEL 9.4+, rootless Podman, user systemd, registry login, Hugging Face token
- **Track 3 (optional):** `podman` or `docker` with Compose — **no** registry or HF token

### Permissions

- **Track 1:** Namespace admin (or equivalent) for Routes, Deployments, Secrets, PVCs
- **Track 2:** User systemd (`systemctl --user`); linger enabled if the host should survive logout
- **Track 3:** Local user only

## Choose your track

| | **Track 1: OpenShift** | **Track 2: RHEL Quadlet** | Track 3: Local mock |
|---|---|---|---|
| **Priority** | **Primary** — cluster deploy | **Primary** — single-host production style | Optional — maintainers / CI |
| **Goal** | Try the real stack on OpenShift | Try the real stack on RHEL + systemd | Validate UI and ingest without RHAII |
| **Time** | ~30–45 min (+ model download) | ~45 min (+ model download) | ~15 min |
| **Inference** | **RHAII 3.5 CPU** | **RHAII 3.5 CPU** | Mock only |
| **Start** | `INFERENCE=rhaii make deploy-openshift` | `systemctl --user enable --now …` | `make demo` |
| **UI** | Dashboard Route `/welcome` | `http://127.0.0.1:8501/welcome` | `http://127.0.0.1:8501/welcome` |

**Customers:** complete **Track 1** or **Track 2**, then **[Hands-on validation](#hands-on-validation)**. Use **Track 3** only when you lack cluster/RHEL capacity or need a fast regression check.

---

## Track 1: Deploy to OpenShift (RHAII CPU)

*~30–45 minutes. **Recommended customer path** — Routes, RHAII 3.5 CPU, optional GuideLLM.*

### Prerequisites

- `oc` logged into a cluster that meets the [RHAII CPU hardware](#rhaii-cpu-hardware-tracks-1-and-2) requirements
- `git`, `make`, `curl`, `python3`
- `export HF_TOKEN="your_huggingface_token"`
- `podman login registry.redhat.io`

### Step 1: Deploy with RHAII CPU

```bash
git clone <repo-url> && cd helpdesk-email-triage
oc new-project helpdesk-email-triage    # once
export HF_TOKEN="your_huggingface_token"
podman login registry.redhat.io
INFERENCE=rhaii make deploy-openshift
```

Weights download to the `rhaii-model-cache` PVC on first start. Increase wait if needed: `RHAII_WAIT_TIMEOUT=1200s INFERENCE=rhaii make deploy-openshift`.

<details>
<summary>Mock on OpenShift (smoke only — not a customer evaluation)</summary>

Use when the cluster cannot run RHAII yet, or for overlay/CI checks:

```bash
INFERENCE=mock make deploy-openshift
```

The inbox welcome pill shows **local mock**. For full UI regression without a cluster, prefer [Track 3](#track-3-local-mock-validation-maintainers).
</details>

### Step 2: Verify deployment

```bash
make verify-openshift
```

You should see **Gateway** and **Dashboard** Route URLs, gateway `/health` JSON (with a real model name when RHAII is up), dashboard headers, and at least one ticket.

Open **`https://<dashboard-route>/welcome`** — the pill should show **RHAII**, not mock.

If the gateway Route is OAuth-protected (hardened overlay), verify uses in-cluster port-forward for API smoke tests — follow the script output.

### Step 3: Complete hands-on validation

Follow **[Hands-on validation](#hands-on-validation)** on the dashboard Route. Use the cluster `VAULT_SECRET` from `helpdesk-secrets` for vault rehydration.

### Step 4: Ingest from outside the cluster

Use the **gateway Route URL** from verify (not `127.0.0.1:8080`):

```bash
GW="https://<gateway-route-host>"
curl -sk -X POST "${GW}/ingest/raw" \
  -H "Content-Type: application/json" \
  -d '{"sender":"you@example.com","subject":"OpenShift test","body":"Charged twice on card ACC-998877."}'
```

When `INGEST_API_KEY` is set (hardened overlay), add `-H "X-Ingest-Key: …"` from `oc get secret helpdesk-secrets …`.

### Step 5: Benchmark inference with GuideLLM

After hands-on validation, run **[Benchmark inference with GuideLLM](#benchmark-inference-with-guidellm)** (OpenShift → `make guidellm-openshift`) to measure RHAII CPU throughput and latency before a pilot.

### What you get on OpenShift

- **RHAII 3.5 CPU** serving `Qwen/Qwen2.5-1.5B-Instruct` on tokenized ticket text
- **Routes** for gateway and dashboard; CORS/WebSockets discovered from the dashboard Route at startup
- **Kustomize overlays** including hardened pilots ([below](#openshift-hardened-pilot))
- **GuideLLM Job** against internal inference Service DNS

### Delete

```bash
make undeploy-openshift
# Remove the whole project:
DELETE_NAMESPACE=1 make undeploy-openshift
```

Full overlay catalog: [docs/deploy-openshift.md](docs/deploy-openshift.md).

---

## Track 2: Run on RHEL with systemd (Quadlet)

*~45 minutes. **Recommended for single-host evaluation** — RHAII 3.5 CPU via user systemd.*

### Prerequisites

- RHEL 9.4+ with rootless Podman meeting [RHAII CPU hardware](#rhaii-cpu-hardware-tracks-1-and-2) requirements
- `podman login registry.redhat.io`
- Hugging Face token and a strong `VAULT_SECRET`

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

### Step 5: Complete hands-on validation

Follow **[Hands-on validation](#hands-on-validation)** at `http://127.0.0.1:8501`. Vault rehydration uses `VAULT_SECRET` from `secrets.env`.

Optional:

```bash
./scripts/ingest-sample.sh
```

### Step 6: Benchmark inference with GuideLLM

With `rhaii-cpu-engine` healthy on `:8000`, follow **[Benchmark inference with GuideLLM](#benchmark-inference-with-guidellm)** (RHEL / Quadlet → `podman run` against `http://127.0.0.1:8000`).

### Stop

```bash
systemctl --user stop agent-dashboard email-gateway rhaii-cpu-engine
```

**Compose alternative** on RHEL (no systemd): see [Production RHEL with Compose](#production-rhel-with-compose) below. Full Quadlet notes: [deploy/quadlet/README.md](deploy/quadlet/README.md).

---

## Hands-on validation

*Complete after **Track 1** or **Track 2**. Same UI and API checks; only URLs and secrets differ.*

| | Track 1 (OpenShift) | Track 2 (Quadlet) |
|---|---|---|
| **Welcome / inbox** | `https://<dashboard-route>/welcome` | `http://127.0.0.1:8501/welcome` |
| **Gateway API** | `https://<gateway-route>` (+ `X-Ingest-Key` if hardened) | `http://127.0.0.1:8080` |
| **Vault secret** | `helpdesk-secrets` / `VAULT_SECRET` | `~/.config/helpdesk/secrets.env` |
| **Welcome pill** | **RHAII** | **RHAII** |

### Step 1: Open the welcome page and inbox

1. Open the welcome URL — pipeline diagram and before/after redaction example.
2. Open the inbox; confirm sample tickets from `sample_emails/` (file watcher).
3. Confirm the welcome pill shows **RHAII** (not mock).

### Step 2: Submit support tickets

Try at least two ingest paths (sidebar **Quick demo scenarios**, custom form, `POST /ingest/raw`, or SMTP where exposed):

```bash
# Track 2 example — use your gateway Route on Track 1
curl -sS -X POST http://127.0.0.1:8080/ingest/raw \
  -H "Content-Type: application/json" \
  -d '{"sender":"you@example.com","subject":"VPN issue","body":"Cannot connect from home office."}'
```

**What to look for:** New tickets in the queue within a few seconds (RHAII classification may take hundreds of ms to a few seconds per ticket).

### Step 3: Review classification by category

1. Filter **Queue** by category and **Urgency** (e.g. `High` for double-charge / MFA samples).
2. Open tickets; confirm **category**, **urgency**, and subject.

Expected results for bundled samples (mock and RHAII should agree on these demos):

| Email | Category | Urgency |
|---|---|---|
| Double charge on card | Billing | High |
| MFA lockout | Account Access | High |
| VPN dropping | Tech Support | Medium |
| GDPR erasure request | General | Low |

### Step 4: Check redaction and the vault

1. Open the **billing / double charge** ticket.
2. **Sanitized body:** tokens `[NAME_1]`, `[EMAIL_1]`, `[CARD_LAST4_1]`, `[PHONE_1]`, `[ACCOUNT_ID_1]` — not raw PII. **From** is tokenized.
3. **View original PII vault** — map matches originals using your deploy secret.
4. **What downstream systems see** — no `original_text` or vault map.

### Step 5: Review classification speed

Note per-ticket **classification time** and **Avg classification** in the inbox. On RHAII CPU, expect higher latency than mock — continue with **[Benchmark inference with GuideLLM](#benchmark-inference-with-guidellm)** for throughput sizing.

### What you accomplished

- End-to-end **ingest → tokenize → RHAII classify → ticket API**
- Verified **category/urgency** and **PII tokenization** on real inference
- Confirmed **vault** and **downstream JSON** contract

---

## Benchmark inference with GuideLLM

*Part of the **customer quickstart** after Track 1 or Track 2 hands-on validation. Requires **RHAII** on port **8000** (not mock).*

[GuideLLM](https://github.com/vllm-project/guidellm) load-tests the **OpenAI-compatible inference endpoint** — the same class of `chat/completions` call the email gateway makes after regex tokenization. Use the results to size CPU nodes and set expectations for classification latency at concurrency.

| Path | When | Command |
|---|---|---|
| **OpenShift** | After `INFERENCE=rhaii` deploy + `make verify-openshift` | `make guidellm-openshift` |
| **RHEL / Quadlet / Compose** | RHAII listening on `127.0.0.1:8000` | `podman run` (below) |

Skip this section on mock-only deploys ([Track 3](#track-3-local-mock-validation-maintainers)).

### Step 1: Pull the GuideLLM image

**OpenShift** — the benchmark Job uses the Red Hat image (same registry login as RHAII CPU):

```bash
podman login registry.redhat.io
# Default: registry.redhat.io/rhai/guidellm-rhel9 (override with GUIDELLM_IMAGE)
```

**RHEL / laptop with local RHAII:**

```bash
podman pull ghcr.io/vllm-project/guidellm:v0.7.1
```

### Step 2: Run the benchmark

#### OpenShift (recommended for Track 1)

Requires `rhaii-cpu` in the namespace (mock overlays are rejected).

```bash
make guidellm-openshift
# Optional tuning:
# GUIDELLM_RATE=1,2,4 GUIDELLM_MAX_SECONDS=300 make guidellm-openshift
```

- Targets **in-cluster Service DNS** (`rhaii-cpu:8000`), not the public gateway Route.
- Creates a results PVC, runs a GuideLLM Job, copies artifacts to `./results/guidellm-openshift/`.
- Red Hat image uses CLI `guidellm run`; upstream `ghcr.io/vllm-project/guidellm` uses `guidellm benchmark run` — set `GUIDELLM_IMAGE` to switch.

Watch progress:

```bash
oc logs -n helpdesk-email-triage -l job-name --follow
```

#### RHEL host, Quadlet, or `compose.yml` (Track 2)

With RHAII healthy on port 8000:

```bash
mkdir -p results/guidellm

podman run --rm --network host \
  -v "$(pwd)/results/guidellm:/results:rw" \
  -e HOME=/results -e HF_HOME=/results/.cache \
  -e HF_TOKEN="${HF_TOKEN}" \
  ghcr.io/vllm-project/guidellm:v0.7.1 \
  benchmark run \
  --target http://127.0.0.1:8000 \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --processor Qwen/Qwen2.5-1.5B-Instruct \
  --data '{"prompt_tokens":128,"output_tokens":64}' \
  --rate-type concurrent --rate 2,4 \
  --max-seconds 120 \
  --output-dir /results \
  --outputs benchmark-results.json,benchmark-results.html
```

On **macOS** with RHAII in Podman, use `--target http://host.containers.internal:8000` (Docker: `host.docker.internal`).

### Step 3: Review results

| Output | Where |
|---|---|
| **Console** | Job log (`oc logs …`) or `podman run` stdout — throughput, TTFT, latency tables |
| **HTML report** | `./results/guidellm-openshift/*.html` or `./results/guidellm/benchmark-results.html` — charts in a browser |
| **JSON** | Matching `.json` files for archival or comparison runs |

Use these numbers alongside per-ticket **classification time** in the inbox when planning pilot capacity.

More detail (NetworkPolicy, env vars, production sweeps): [docs/deploy-openshift.md](docs/deploy-openshift.md#load-test-inference-guidellm) · [Red Hat GuideLLM on Kubernetes](https://developers.redhat.com/articles/2025/12/24/how-deploy-and-benchmark-vllm-guidellm-kubernetes).

---

## Track 3: Local mock validation (maintainers)

*~15 minutes. **Not a customer evaluation path** — mock classifier, no registry or HF token. Use for UI smoke tests, docs screenshots, and `make compose-e2e` / CI.*

### Prerequisites

- `podman` or `docker` with Compose, `make`, `curl`, `python3`

### Step 1: Start the mock stack

```bash
git clone <repo-url> && cd helpdesk-email-triage
make demo
```

Gateway `:8080`, dashboard `:8501`, SMTP `:3025`. Sample mail ingests automatically. Welcome pill shows **local mock**.

```bash
curl -sS http://127.0.0.1:8080/health   # classify_model: mock-triage
```

### Step 2: Smoke-test the inbox

Walk **[Hands-on validation](#hands-on-validation)** at `http://127.0.0.1:8501`. Vault demo secret: `helpdesk-demo-secret`.

Optional maintainer checks: stop mock inference (`podman stop helpdesk-inference-mock`) and confirm **heuristic-fallback** ingest.

```bash
make down
```

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

# RHAII CPU + hardening (recommended pilot):
INFERENCE=rhaii OVERLAY=deploy/openshift/overlays/hardened make deploy-openshift

# Mock + hardening (overlay smoke only):
OVERLAY=deploy/openshift/overlays/hardened INFERENCE=mock make deploy-openshift
```

> `OVERLAY=.../hardened` without `INFERENCE=rhaii` deploys **mock** inference.

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
