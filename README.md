# Helpdesk email triage with tokenized PII

Classify support email by **category** and **urgency** while keeping raw PII out of logs, models, and downstream tools. Structured data (cards, phones, SSNs, emails) is swapped for reversible tokens in a local vault before anything reaches inference.

**Runs on:** your laptop (mock AI, no registry), a RHEL host (Red Hat AI Inference on CPU), or OpenShift.

**Authors:** Maryam Tahhan · Anton Ivanov · Michael Dawson

---

## Try it now (about 2 minutes)

No GPU, Hugging Face token, or Red Hat registry required.

```bash
git clone <repo-url> && cd helpdesk-email-triage
make demo
```

1. Open **[http://127.0.0.1:8501](http://127.0.0.1:8501)** — sample tickets from `sample_emails/` load automatically.
2. Click a **Quick demo scenario** in the sidebar to triage more mail.
3. Open a ticket — see category, urgency, and **sanitized body** with tokens like `[NAME_1]` instead of real values.
4. Expand **View original PII vault** to rehydrate the original text (demo secret: `helpdesk-demo-secret`).

Stop the stack: `make down`

<details>
<summary>Verify from the terminal (optional)</summary>

```bash
curl -sS http://127.0.0.1:8080/health
curl -sS http://127.0.0.1:8080/tickets | python3 -m json.tool | head -10
```

</details>

Continue with the [Quickstart walkthrough](#quickstart-walkthrough) below to submit tickets, review classification and redaction, and optionally load-test inference.

---

## Quickstart walkthrough

Use this after the stack is running (`make demo` on a laptop, or `make deploy-openshift` + `make verify-openshift` on OpenShift). Open the agent inbox at **http://127.0.0.1:8501** (laptop) or the dashboard Route URL printed by `verify-openshift`.

### Submit support tickets

Try each ingest path at least once:

| Method | How |
|---|---|
| **File watcher** | Sample `.eml` files in `sample_emails/` are ingested automatically on start |
| **Sidebar scenarios** | Click a **Quick demo scenario** (billing, MFA lockout, VPN, etc.) |
| **Custom message** | Sidebar form → enter sender / subject / body → **Triage →** |
| **HTTP API** | `POST /ingest/raw` or upload `.eml` via `POST /ingest` ([example below](#gateway-api-integrators)) |
| **SMTP** | Sidebar **↪** buttons, or send to `support@helpdesk.local` on port **3025** |

```bash
# Optional: ingest from the terminal (add -H "X-Ingest-Key: …" when INGEST_API_KEY is set)
curl -sS -X POST http://127.0.0.1:8080/ingest/raw \
  -H "Content-Type: application/json" \
  -d '{"sender":"you@example.com","subject":"VPN issue","body":"Cannot connect from home office."}'
```

On OpenShift, use the gateway Route URL from `make verify-openshift` instead of `127.0.0.1:8080`, and include `X-Ingest-Key` when the hardened overlay is deployed.

### Review classified and redacted emails

#### Step 1: Review the email in the different inboxes based on classification

1. In the sidebar, set **Queue** to each category: `Billing`, `Tech Support`, `Account Access`, `General`, then `All`.
2. Narrow **Urgency** to `High` only — confirm urgent tickets (double charge, MFA lockout) surface first.
3. Click tickets in the left **Queue** column; detail opens on the right with **category**, **urgency**, and subject.
4. Expand **Category breakdown** above the queue to see distribution across categories.

Expected sample results (file-watcher emails):

| Email | Category | Urgency |
|---|---|---|
| Double charge on card | Billing | High |
| MFA lockout | Account Access | High |
| VPN dropping | Tech Support | Medium |
| GDPR erasure request | General | Low |

#### Step 2: Check redaction

1. Open a ticket with obvious PII (e.g. billing double-charge).
2. In **Sanitized body**, confirm structured PII appears as tokens (`[NAME_1]`, `[CARD_LAST4_1]`, `[PHONE_1]`) — not raw values.
3. Click **🔓 View original PII vault** — compare the token map to the original body (demo secret: `helpdesk-demo-secret` when using default compose).
4. Expand **📤 What downstream systems see** — this is the exact `GET /tickets/{id}` JSON a webhook or CRM would receive; it must not contain `original_text` or the vault.

### Review classification speed

1. In the queue list, each ticket shows **classification time** (e.g. `42 ms classification`).
2. At the top of the inbox, check **Avg classification** in the metrics row.
3. In ticket detail, note the per-ticket latency tag next to the timestamp.
4. On mock inference, times are typically tens of milliseconds; on RHAII CPU, expect hundreds of ms to a few seconds depending on hardware and cold start.

```bash
# API view of the same field
curl -sS http://127.0.0.1:8080/tickets | python3 -c \
  'import json,sys; t=json.load(sys.stdin); print([(x["id"], x.get("classification_ms")) for x in t[:5]])'
```

### Testing classification and redaction quality

1. **Custom PII patterns** — submit a message with a card number, phone, and email; verify each becomes a distinct token in the sanitized body and appears in the vault map.
2. **Category sanity** — billing language → `Billing`; access/MFA → `Account Access`; VPN/outage → `Tech Support`.
3. **Residual names** — RHAII may add `[NAME_N]` tokens; the gateway merge step rejects model output that drops structured tokens or reintroduces raw PII.
4. **Heuristic fallback** — stop inference (`podman stop helpdesk-inference-mock` on laptop); ingest still works and `model` shows `heuristic-fallback`.
5. **Regression** — run `make test` for automated API and pipeline checks.

More UI detail: [docs/testing-locally.md](docs/testing-locally.md).

### Load testing

Load-test the **inference endpoint** (OpenAI-compatible `:8000`) with [GuideLLM](https://github.com/vllm-project/guidellm). This measures RHAII or mock throughput/latency under concurrent chat completions — the same class of call the gateway makes after regex tokenization.

For end-to-end ingest load, run parallel `POST /ingest/raw` requests against port **8080** (add `X-Ingest-Key` when configured).

#### Step 1: Install GuideLLM

```bash
python3 -m venv .venv-guidellm
source .venv-guidellm/bin/activate
pip install 'guidellm[recommended]'
guidellm --version
```

#### Step 2: Run load test

With `make demo` running, the mock inference service is exposed on port **8000**:

```bash
guidellm benchmark run \
  --target http://127.0.0.1:8000 \
  --backend-type openai_http \
  --model mock-triage \
  --rate-type concurrent --rate 4 \
  --max-requests 40 \
  --data 'kind=synthetic_text,prompt_tokens=128,output_tokens=64'
```

For RHAII (`compose.yml` or OpenShift `INFERENCE=rhaii`), use `--model Qwen/Qwen2.5-1.5B-Instruct` and point `--target` at the inference Service (port-forward or in-cluster URL). See [Red Hat Developer: benchmark vLLM with GuideLLM](https://developers.redhat.com/articles/2025/12/24/how-deploy-and-benchmark-vllm-guidellm-kubernetes).

#### Step 3: Review results

GuideLLM prints a summary table: request throughput, time-to-first-token, and end-to-end latency at the chosen concurrency. Use it to compare mock vs RHAII CPU, tune replica counts on OpenShift, or validate a node size before a pilot.

### What you've accomplished

- Deployed a **local helpdesk triage pipeline** (ingest → tokenize → classify → ticket API).
- Submitted mail via **multiple ingest paths** and confirmed tickets in the agent inbox.
- Verified **category and urgency** labels and filtered the queue by classification.
- Confirmed **PII redaction** in downstream JSON while retaining authorized vault rehydration.
- Observed **classification latency** per ticket and in aggregate.
- Optionally **benchmarked inference** with GuideLLM or parallel HTTP ingest.

**Laptop tear-down:** `make down`

**OpenShift tear-down:** `make undeploy-openshift` (or `DELETE_NAMESPACE=1 make undeploy-openshift` to remove the project)

---

## What should I do next?

| If you want to… | Do this |
|---|---|
| **Explore the demo UI** | You're done — see [docs/testing-locally.md](docs/testing-locally.md) for every sidebar feature |
| **Wire your own queue / CRM** (no UI) | `make gateway-only` → [docs/integration.md](docs/integration.md) |
| **Run real AI on a RHEL host** | [Production RHEL](#production-rhel) below |
| **Deploy to OpenShift** | [OpenShift quick deploy](#openshift-quick-deploy) below |
| **Harden for a production pilot** | [OpenShift hardened](#openshift-hardened) below |
| **Run tests / CI locally** | `make lint && make test && make compose-e2e` |

---

## How it works

![Four-stage pipeline: ingestion via HTTP, SMTP, or file drop → email gateway tokenizes PII into a vault → RHAII or mock classifies on sanitized text → optional Streamlit agent inbox](docs/images/architecture-overview.svg)

1. **Ingest** — SMTP `:3025`, HTTP `:8080` (`POST /ingest`, `/ingest/raw`), or file watcher on `.eml` drops.
2. **Gateway** — Regex-tokenizes structured PII into a vault keyed by ticket ID. Exposes `TriageResult` JSON.
3. **Inference** — RHAII 3.5 on CPU (production) or built-in mock (laptop / CI). Sees **tokenized text only**.
4. **Agent inbox** *(optional)* — Streamlit demo UI on `:8501`. Integrators can skip this and poll the API or use webhooks.

**Privacy guarantee:** Raw card numbers, phones, and names never reach the model. Downstream systems get tokens; authorized agents rehydrate from the vault locally.

---

## Production RHEL

Real Red Hat AI Inference on CPU with the full stack (gateway + UI):

```bash
cp .env.example .env
podman login registry.redhat.io
export HF_TOKEN="your_huggingface_token"
export RHEL_CACHE_DIR="$HOME/rhaii-cache" && mkdir -p "$RHEL_CACHE_DIR"
podman compose -f compose.yml up --build -d
```

First start downloads model weights (several minutes). Open [http://127.0.0.1:8501](http://127.0.0.1:8501).

For systemd instead of Compose: [deploy/quadlet/README.md](deploy/quadlet/README.md).

---

## OpenShift quick deploy

```bash
oc new-project helpdesk-email-triage    # once
export HF_TOKEN="your_huggingface_token"   # optional — mock used if missing
podman login registry.redhat.io            # optional — mock used if missing
make deploy-openshift
```

### Validate deployment

```bash
make verify-openshift    # gateway health, dashboard headers, ingest/ticket smoke test
```

Note the **Gateway** and **Dashboard** URLs in the output, then continue with [Submit support tickets](#submit-support-tickets) in the walkthrough above.

| Goal | Command |
|---|---|
| Demo (auto: mock or RHAII) | `make deploy-openshift` |
| Force mock | `INFERENCE=mock make deploy-openshift` |
| Force RHAII CPU | `INFERENCE=rhaii make deploy-openshift` |

### Tear down

```bash
make undeploy-openshift
# Remove the whole project: DELETE_NAMESPACE=1 make undeploy-openshift
```

Full runbook (overlays, `INFERENCE` vs `OVERLAY`, Kind CI): [docs/deploy-openshift.md](docs/deploy-openshift.md)

### OpenShift hardened

For pilots beyond demo defaults — NetworkPolicies, dashboard OAuth, non-demo secrets:

```bash
export VAULT_SECRET="$(openssl rand -hex 32)"
export INGEST_API_KEY="$(openssl rand -hex 16)"
oc create secret generic helpdesk-secrets \
  --from-literal=VAULT_SECRET="$VAULT_SECRET" \
  --from-literal=INGEST_API_KEY="$INGEST_API_KEY" \
  -n helpdesk-email-triage --dry-run=client -o yaml | oc apply -f -

# Mock + hardening:
OVERLAY=deploy/openshift/overlays/hardened make deploy-openshift

# RHAII CPU + hardening (also set HF_TOKEN and registry login):
INFERENCE=rhaii OVERLAY=deploy/openshift/overlays/hardened make deploy-openshift
```

> `OVERLAY=.../hardened` alone deploys **mock** inference. Add `INFERENCE=rhaii` for RHAII CPU.

HTTP ingest then requires header `X-Ingest-Key`. Pin images: `IMAGE_TAG=v1.2.3 make deploy-openshift`.

---

## Gateway API (integrators)

The reusable product is `email-gateway/` — Streamlit is optional.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness |
| `POST /ingest` | Upload `.eml` file |
| `POST /ingest/raw` | JSON `{sender, subject, body}` |
| `GET /tickets` | List triaged tickets (`TriageResult` JSON) |
| `GET /tickets/{id}/vault` | Rehydrate PII — header `X-Vault-Secret` |

**Ports:** HTTP `8080` · SMTP `3025` · inference `8000` · dashboard `8501`

**Push delivery:** `TICKET_SINK=webhook:https://your-system/hook` (optional HMAC via `TICKET_SINK_SECRET`)

```bash
curl -sS -X POST http://127.0.0.1:8080/ingest/raw \
  -H "Content-Type: application/json" \
  -d '{"sender":"demo@example.com","subject":"VPN down","body":"Cannot connect from home."}'
```

Full API reference, webhook signing, and SMTP patterns: [docs/integration.md](docs/integration.md)

---

## Configuration

Copy defaults once: `cp .env.example .env`

| Variable | What it does |
|---|---|
| `VAULT_SECRET` | Gates vault rehydration — **change before production** |
| `INGEST_API_KEY` | When set, requires `X-Ingest-Key` on HTTP ingest |
| `REQUIRE_SECRETS` | Set `1` to refuse demo-default secrets (hardened overlay) |
| `MODEL_NAME` | `Qwen/Qwen2.5-1.5B-Instruct` (RHAII) or `mock-triage` (demo) |
| `TICKET_SINK` | `webhook:https://…` or `log` for push delivery |
| `HF_TOKEN` | Hugging Face token — required for RHAII |
| `INFERENCE` | OpenShift only: `auto`, `mock`, or `rhaii` |
| `IMAGE_TAG` | Pin container tags on OpenShift deploy |

See `.env.example` for the full list.

---

## Documentation

| Guide | When to read it |
|---|---|
| [docs/testing-locally.md](docs/testing-locally.md) | Walkthrough of every demo UI feature |
| [docs/integration.md](docs/integration.md) | Full HTTP/SMTP API, webhooks, compose matrix |
| [docs/deploy-openshift.md](docs/deploy-openshift.md) | OpenShift overlays, production checklist, Kind CI |
| [docs/customer-ci.md](docs/customer-ci.md) | Fork the repo, Quay publish, pipeline adoption |
| [deploy/openshift/README.md](deploy/openshift/README.md) | Kustomize layout and manifest notes |
| [deploy/quadlet/README.md](deploy/quadlet/README.md) | systemd / Quadlet on a single RHEL host |

---

## Development

```bash
make test              # unit tests (no running stack)
make test-webhook      # webhook sink e2e
make compose-e2e       # full mock-stack smoke test
make validate-manifests
make build-images      # build all three Containerfiles
```

**CI** (on every PR): ruff lint, tests, compose e2e, kind e2e, container builds. CI uses mock inference only — not `registry.redhat.io`.

**Published images** (Quay): `helpdesk-email-gateway` · `helpdesk-triage-ui` · `helpdesk-inference-mock` under `quay.io/mtahhan/`.

```
.
├── email-gateway/          # Reusable gateway (API, SMTP, tokenization, vault)
├── agent-dashboard/        # Streamlit demo inbox (optional)
├── inference-mock/         # OpenAI-compatible mock for laptops and CI
├── sample_emails/          # Demo .eml files (fictional PII)
├── compose*.yml            # Laptop / RHEL stacks
├── deploy/openshift/       # Kustomize for OpenShift
├── deploy/quadlet/         # systemd units for RHEL
└── scripts/                # Deploy, verify, ingest helpers
```

---

## References

- [Red Hat AI Inference 3.5 — CPU inference](https://docs.redhat.com/en/documentation/red_hat_ai_inference/3.5/html/getting_started/about-cpu-inference_getting-started)
- [AI quickstart catalog](https://docs.redhat.com/en/learn/ai-quickstarts)
- [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct)
