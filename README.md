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
make verify-openshift                      # prints Route URLs + smoke test
```

| Goal | Command |
|---|---|
| Demo (auto: mock or RHAII) | `make deploy-openshift` |
| Force mock | `INFERENCE=mock make deploy-openshift` |
| Force RHAII CPU | `INFERENCE=rhaii make deploy-openshift` |

Tear down: `make undeploy-openshift`

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
