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

Load-test the **RHAII inference endpoint** (OpenAI-compatible `:8000`) with [GuideLLM](https://github.com/vllm-project/guidellm). This measures throughput/latency under concurrent chat completions — the same class of call the gateway makes after regex tokenization.

For end-to-end ingest load, run parallel `POST /ingest/raw` requests against port **8080** (add `X-Ingest-Key` when configured).

#### Step 1: Pull the GuideLLM container image

No local Python install — use the same image as [Red Hat's GuideLLM on Kubernetes guide](https://developers.redhat.com/articles/2025/12/24/how-deploy-and-benchmark-vllm-guidellm-kubernetes):

```bash
podman pull ghcr.io/vllm-project/guidellm:v0.7.1
# or: docker pull ghcr.io/vllm-project/guidellm:v0.7.1
```

On OpenShift the cluster pulls `registry.redhat.io/rhai/guidellm-rhel9` when the benchmark Job starts (`make guidellm-openshift`; same `registry.redhat.io` login as RHAII CPU).

#### Step 2: Run load test

**Laptop / RHEL host** — with `compose.yml` (RHAII) running, inference is on port **8000**:

```bash
mkdir -p results/guidellm

# Linux / RHEL — RHAII on localhost:8000
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

On **macOS** (Podman/Docker Desktop), use `http://host.containers.internal:8000` (Podman) or `http://host.docker.internal:8000` (Docker) for `--target` instead of `--network host`.

**OpenShift** — requires an **RHAII** deploy (`rhaii-cpu`). After `make verify-openshift` on a rhaii-demo or hardened-rhaii overlay:

```bash
make guidellm-openshift
# or: ./scripts/guidellm-openshift.sh helpdesk-email-triage
```

The script:

- Benchmarks via **internal Service DNS** (`http://rhaii-cpu.<namespace>.svc.cluster.local:8000`) — not the public Route
- Creates a **results PVC**, applies the GuideLLM **NetworkPolicy**, and runs `registry.redhat.io/rhai/guidellm-rhel9:3.5.0-1787154406` (`guidellm run` — JSON + HTML in one Job)
- Copies `benchmark-results.json` and `.html` to `./results/guidellm-openshift/`

Tune with `GUIDELLM_RATE`, `GUIDELLM_MAX_SECONDS`, `GUIDELLM_MODEL`, `GUIDELLM_WAIT_TIMEOUT`, or `GUIDELLM_IMAGE` (override with upstream `ghcr.io/vllm-project/guidellm` if needed). For a longer production-style sweep matching the article: `GUIDELLM_RATE=1,2,4 GUIDELLM_MAX_SECONDS=300 make guidellm-openshift`.

For end-to-end **gateway** load on OpenShift, send parallel `POST /ingest/raw` requests to the gateway Route (include `X-Ingest-Key` when the hardened overlay is used).

#### Step 3: Review results

- **Console** — throughput, TTFT, and latency tables print in the Job log (`oc logs job/...` or the script output).
- **HTML report** — open `./results/guidellm-openshift/<job>.html` in a browser for the interactive GuideLLM UI (latency charts, token stats).
- **JSON** — `./results/guidellm-openshift/<job>.json` for archival or `guidellm benchmark from-file` (see the [Red Hat article Step 3](https://developers.redhat.com/articles/2025/12/24/how-deploy-and-benchmark-vllm-guidellm-kubernetes)).

Use the numbers to size RHAII CPU nodes before a pilot.

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

![Four-stage pipeline: ingestion via HTTP, SMTP, or file drop → email gateway tokenizes PII into a vault → RHAII (production) or mock (demo/CI) classifies on sanitized text → optional Streamlit agent inbox; GuideLLM benchmarks RHAII on OpenShift](docs/images/architecture-overview.svg)

1. **Ingest** — HTTP `:8080` (`POST /ingest`, `/ingest/raw`; `X-Ingest-Key` when hardened), SMTP `:3025` (demo), or file watcher on `.eml` drops.
2. **Gateway** — Regex-tokenizes structured PII into a vault keyed by ticket ID. Exposes `TriageResult` JSON and `/health/ready`.
3. **Inference** — RHAII 3.5 CPU on OpenShift/RHEL (production) or built-in mock (laptop demo / CI). Sees **tokenized text only**. GuideLLM load tests target RHAII only.
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

For pilots beyond demo defaults — NetworkPolicies, OAuth on gateway and dashboard Routes, non-demo secrets:

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
| `GET /health/ready` | Readiness (inference reachable) |
| `POST /ingest` | Upload `.eml` file |
| `POST /ingest/raw` | JSON `{sender, subject, body}` |
| `GET /tickets` | List tickets — `?limit=` / `?offset=`; `X-Ingest-Key` when configured |
| `GET /tickets/{id}` | Single ticket — `X-Ingest-Key` when configured |
| `GET /tickets/{id}/vault` | Rehydrate PII — `X-Vault-Secret` or `X-Ingest-Key` |

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
| `INGEST_API_KEY` | When set, requires `X-Ingest-Key` on ingest and ticket list endpoints |
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
| [Quickstart walkthrough](#quickstart-walkthrough) | Submit tickets, review redaction, GuideLLM load test |
| [docs/testing-locally.md](docs/testing-locally.md) | Every demo UI feature in detail |
| [docs/integration.md](docs/integration.md) | Full HTTP/SMTP API, auth, webhooks, compose matrix |
| [docs/deploy-openshift.md](docs/deploy-openshift.md) | OpenShift overlays, verify, GuideLLM, production checklist |
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
make test-openshift-overlay   # overlay / INFERENCE consistency (no cluster)
make build-images      # build all three Containerfiles
make guidellm-openshift     # GuideLLM benchmark Job (OpenShift + RHAII only)
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
