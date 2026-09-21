# Quickstart walkthrough

**Catalog reviewers:** the hands-on checklist ([Submit support tickets](../README.md#submit-support-tickets) → [What you've accomplished](../README.md#what-youve-accomplished), including [Load testing](../README.md#load-testing)) lives in **README Track 1** between verify and delete. This document mirrors the same sections for deep links.

Use this after the stack is running:

| Environment | How to start | UI |
|---|---|---|
| **OpenShift (RHAII)** | `INFERENCE=rhaii make deploy-openshift` then `make verify-openshift` | Dashboard Route `/welcome` |
| **RHEL Quadlet** | Quadlet units — [deploy/quadlet/README.md](../deploy/quadlet/README.md) | `http://127.0.0.1:8501/welcome` |
| **Local mock (maintainers)** | [CONTRIBUTING.md](../CONTRIBUTING.md#local-mock-validation) — `make demo` | `http://127.0.0.1:8501/welcome` |
| **RHEL Compose** | `podman compose -f compose.yml up` | `http://127.0.0.1:8501` |

**OpenShift:** use the **gateway Route URL** from `make verify-openshift` instead of `127.0.0.1:8080`. Add header `X-Ingest-Key` when the hardened overlay is deployed.

**UI reference:** every sidebar and panel is described in [testing-locally.md](testing-locally.md).

---

## Submit support tickets

Try each ingest path at least once:

| Method | How |
|---|---|
| **File watcher** | Sample `.eml` files in `sample_emails/` are ingested automatically on start |
| **Sidebar scenarios** | Click a **Quick demo scenario** (billing, MFA lockout, VPN, etc.) |
| **Custom message** | Sidebar form → enter sender / subject / body → **Triage →** |
| **HTTP API** | `POST /ingest/raw` or upload `.eml` via `POST /ingest` ([integration.md](integration.md)) |
| **SMTP** | Sidebar **↪** buttons, or send to `support@helpdesk.local` on port **3025** |

```bash
# Laptop — add -H "X-Ingest-Key: …" when INGEST_API_KEY is set
curl -sS -X POST http://127.0.0.1:8080/ingest/raw \
  -H "Content-Type: application/json" \
  -d '{"sender":"you@example.com","subject":"VPN issue","body":"Cannot connect from home office."}'
```

---

## Review classified and redacted emails

### Step 1: Review the email in the different inboxes based on classification

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

### Step 2: Check redaction

1. Open a ticket with obvious PII (e.g. billing double-charge).
2. In **Sanitized body**, confirm structured PII appears as tokens (`[NAME_1]`, `[EMAIL_1]`, `[CARD_LAST4_1]`, `[PHONE_1]`, `[ACCOUNT_ID_1]` for `ACC-…` patterns) — not raw values.
3. Check **From** on the ticket — the gateway tokenizes the sender address (e.g. `[EMAIL_1]`), not the raw mailbox.
4. Click **🔓 View original PII vault** — compare the token map to the original body (demo secret: `helpdesk-demo-secret` when using default compose).
5. Expand **📤 What downstream systems see** — exact `GET /tickets/{id}` JSON for webhooks/CRMs; it must not contain `original_text` or the vault.

---

## Review classification speed

1. In the queue list, each ticket shows **classification time** (e.g. `42 ms classification`).
2. At the top of the inbox, check **Avg classification** in the metrics row.
3. In ticket detail, note the per-ticket latency tag next to the timestamp.
4. On mock inference, times are typically tens of milliseconds; on RHAII CPU, expect hundreds of ms to a few seconds depending on hardware and cold start.

```bash
curl -sS http://127.0.0.1:8080/tickets | python3 -c \
  'import json,sys; t=json.load(sys.stdin); print([(x["id"], x.get("classification_ms")) for x in t[:5]])'
```

---

## Testing classification and redaction quality

1. **Custom PII patterns** — submit a message with a card number, phone, email, and `ACC-12345` account id; verify distinct tokens in the sanitized body and vault map.
2. **Category sanity** — billing language → `Billing`; access/MFA → `Account Access`; VPN/outage → `Tech Support`.
3. **Residual names** — RHAII may add `[NAME_N]` tokens; the gateway merge step rejects model output that drops structured tokens or reintroduces raw PII.
4. **Heuristic fallback** — stop inference (`podman stop helpdesk-inference-mock` on laptop); ingest still works and `model` shows `heuristic-fallback`.
5. **Regression** — run `make test` for automated API and pipeline checks.

---

## Load testing

**Canonical steps:** [README — Load testing](../README.md#load-testing).

Load-test the **RHAII inference endpoint** (OpenAI-compatible `:8000`) with [GuideLLM](https://github.com/vllm-project/guidellm). Mock-only laptop demos skip this section unless you run `compose.yml` with RHAII.

For end-to-end **gateway** load, run parallel `POST /ingest/raw` against the gateway (add `X-Ingest-Key` when configured).

### Step 1: Install / pull GuideLLM

**RHEL / Quadlet (RHAII on port 8000)** — same Red Hat image as OpenShift:

```bash
podman login registry.redhat.io
podman pull registry.redhat.io/rhai/guidellm-rhel9:3.5.0-1787154406
```

**OpenShift (RHAII overlay):** the cluster pulls `registry.redhat.io/rhai/guidellm-rhel9` when you run `make guidellm-openshift` (same registry login as RHAII CPU). See [deploy-openshift.md — Load test inference](deploy-openshift.md#load-test-inference-guidellm).

### Step 2: Run load test

**RHEL / Quadlet** — after `make quadlet-up`:

```bash
make guidellm-quadlet
```

**Compose on laptop** (`compose.yml` with RHAII) — same Red Hat image and CLI:

```bash
make guidellm-quadlet
# or GUIDELLM_TARGET=http://host.containers.internal:8000 make guidellm-quadlet   # macOS Podman
```

**OpenShift:**

```bash
make guidellm-openshift
```

Benchmarks via in-cluster Service DNS (not the public Route). Results land in `./results/guidellm-openshift/`. Tune with `GUIDELLM_RATE`, `GUIDELLM_MAX_SECONDS`, `GUIDELLM_MODEL`, etc. (see [deploy-openshift.md](deploy-openshift.md)).

### Step 3: Review results

- **Console** — throughput and latency in Job logs (`oc logs -n helpdesk-email-triage job/<name>`; name printed by `make guidellm-openshift`).
- **HTML** — open the `.html` report for charts.
- **JSON** — archive or compare runs.

Use the numbers to size RHAII CPU before a pilot.

---

## What you've accomplished

- Deployed a **helpdesk triage pipeline** (ingest → tokenize → classify → ticket API).
- Submitted mail via **multiple ingest paths** and confirmed tickets in the agent inbox.
- Verified **category and urgency** and filtered the queue by classification.
- Confirmed **PII redaction** (including sender and `ACC-…` account ids) in downstream JSON while retaining authorized vault rehydration.
- Observed **classification latency** per ticket and in aggregate.
- Optionally **benchmarked inference** with GuideLLM (RHAII) or parallel HTTP ingest.

**Laptop tear-down:** `make down`

**OpenShift tear-down:** `make undeploy-openshift` (or `DELETE_NAMESPACE=1 make undeploy-openshift` to remove the project)
