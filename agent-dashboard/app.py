"""Support agent inbox for tokenized, AI-triaged helpdesk email."""

from __future__ import annotations

import html
import json
import pathlib
import re
from datetime import datetime

import streamlit as st
from dashboard_api import (
    SMTP_HOST,
    SMTP_PORT,
    check_gateway,
    fetch_tickets,
    fetch_vault,
    ingest_text,
    reply_recipient,
    send_via_smtp,
)
from dashboard_render import (
    PAGE_CSS,
    category_bars_html,
    highlight_originals,
    highlight_tokens,
    render_reply_actions,
    token_table_html,
)
from dashboard_samples import SAMPLE_SCENARIOS

CATEGORIES = ("All", "Billing", "Tech Support", "Account Access", "General")


def _load_arch_svg() -> str:
    for p in (
        pathlib.Path(__file__).parent.parent / "docs" / "images" / "architecture-overview.svg",
        pathlib.Path("/app/docs/images/architecture-overview.svg"),
    ):
        try:
            return p.read_text(encoding="latin-1")
        except OSError:
            continue
    return ""


_ARCH_SVG = _load_arch_svg()
URGENCY_COLOR = {"High": "#C9190B", "Medium": "#F0AB00", "Low": "#3E8635"}
URGENCY_ICON = {"High": "🔴", "Medium": "🟡", "Low": "🟢"}

st.set_page_config(
    page_title="Helpdesk triage inbox",
    page_icon="🎫",
    layout="wide",
)
st.markdown(PAGE_CSS, unsafe_allow_html=True)

# ── Static header ─────────────────────────────────────────────────────
st.title("Helpdesk triage inbox")
st.caption(
    "Local CPU classification · Red Hat AI Inference 3.5 · Tokenized PII"
)
st.markdown(
    '<div class="ai-banner">'
    "<strong>AI-generated content.</strong> "
    "Category, urgency, and sanitized text are produced by a local language model. "
    "Redaction can miss entities — verify before routing to downstream systems."
    "</div>",
    unsafe_allow_html=True,
)

with st.expander("ℹ️ How to use this demo", expanded=False):
    st.markdown(
        """
**This dashboard shows what happens when a support email passes through an AI triage pipeline running entirely on local CPUs — no GPU, no cloud.**

---

#### The pipeline (what happens to every email)

1. **Ingest** — an email arrives via the file watcher, SMTP (port 3025), or the sidebar form.
2. **Regex tokenization** — structured PII (card numbers, phone numbers, SSNs, email addresses, account IDs, and RFC-822 display names) is immediately replaced with tokens: `[CARD_LAST4_1]`, `[PHONE_1]`, `[EMAIL_1]`, etc. The originals go into a private vault keyed by ticket ID. Regex is used here because GDPR/HIPAA/GLBA require deterministic, auditable controls.
3. **RHAII classification** — the *regex-tokenized* body is sent to Red Hat AI Inference 3.5 (vLLM on CPU, or the local mock). RHAII returns `category`, `urgency`, a one-line `summary`, and `sanitized_text` with any residual person names replaced (`[NAME_1]`, `[NAME_2]`, …). A safety merge verifies that RHAII didn't drop any structured token or reintroduce raw PII before accepting its body output; the summary is gated the same way. Residual names may remain as raw text if the merge rejects the model's output.
4. **Ticket created** — the sanitized body + AI labels appear in the queue under a **Ticket ID**. That ticket ID is the secure link back to all original contact details in the vault. Downstream systems only ever see the tokenized text; authorized agents rehydrate the sender and body from the vault when they need to reply.

> **How does an agent know who to respond to?**
> The sanitized body is stripped of identifying details so it can flow through untrusted channels safely. An agent reads the sender from the ticket envelope (the `From:` header, shown in the ticket detail above the body), not from the sanitized text. The vault maps each `[TOKEN]` back to the original value, so an authorized representative can recover the full context — name, phone, card tail — without raw PII ever appearing in downstream logs. In an enterprise deployment the ticket ID maps directly to a CRM record (e.g. Salesforce, ServiceNow) that already holds the customer's contact details.

---

#### Navigating the UI

| Area | What it does |
|---|---|
| **Queue (left column)** | Filtered list of tickets, newest first.  Click a ticket to open it. |
| **Ticket detail (right column)** | Shows category, urgency, SLA ms, and the sanitized body with PII tokens highlighted in blue. |
| **Downstream payload** | Expand **📤 What downstream systems see** to view the exact `GET /tickets/{id}` JSON — the contract for queues, webhooks, and CRM adapters. |
| **Authorized rehydration** | Click **🔓 View original PII vault** to see original body (PII highlighted red) vs sanitized body (tokens in blue) side by side. After the vault is open, use **Reply via email** to launch a `mailto:` draft to the original sender. Click 🔒 to close. State resets when you switch tickets. |
| **Filters (sidebar)** | Narrow the queue by category or urgency. |
| **Quick demo scenarios (sidebar)** | One-click triage of 4 pre-built emails covering Billing, Account Access, Tech Support, and General. No command line needed. |
| **Custom message (sidebar)** | Type any sender / subject / body and click **Triage →** to see a live classification. |

---

#### What to look for

- **PII tokens in the sanitized body** — `[NAME_1]` replaces the customer's name; `[CARD_LAST4_1]` replaces the card number. Only these tokens reach downstream queues.
- **Vault rehydration** — the token map shows exactly which token maps to which original value. This is gated behind an authorization checkbox to mirror a real CRM permission model.
- **Classification ms** — the SLA tag shows how fast the local CPU inference completed the request.
- **Heuristic fallback** — if the inference endpoint is down, the model field shows `heuristic-fallback`; ingest still works.
        """,
        unsafe_allow_html=False,
    )
    if _ARCH_SVG:
        st.markdown("#### Architecture")
        st.markdown(
            f'<div style="overflow-x:auto;margin-top:0.5rem">{_ARCH_SVG}</div>',
            unsafe_allow_html=True,
        )


# ── Sidebar ───────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    st.selectbox("Queue", CATEGORIES, key="category_filter")
    st.multiselect(
        "Urgency",
        ["High", "Medium", "Low"],
        default=["High", "Medium", "Low"],
        key="urgency_filter",
    )

    st.markdown("---")
    _sidebar_tickets = fetch_tickets()
    _sidebar_model = (
        _sidebar_tickets[0].get("model", "—") if _sidebar_tickets else "—"
    )
    st.markdown(
        f"**Model** &nbsp; `{_sidebar_model}`", unsafe_allow_html=True
    )

    st.markdown("---")
    st.subheader("Quick demo scenarios")
    st.caption("Triage a sample email instantly:")
    for label, scenario in SAMPLE_SCENARIOS.items():
        if st.button(label, use_container_width=True, key=f"demo_{label}"):
            with st.spinner(f"Triaging: {scenario['subject']}…"):
                try:
                    created = ingest_text(**scenario)
                    fetch_tickets.clear()
                    st.session_state["selected"] = created["id"]
                    st.success(f"Created {created['id']}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Failed: {exc}")

    st.markdown("---")
    st.subheader("SMTP ingest")
    st.caption(f"Send direct to SMTP listener ({SMTP_HOST}:{SMTP_PORT}):")
    for smtp_label in ("💳 Double charge", "🔒 MFA lockout"):
        if st.button(
            f"↪ {smtp_label}",
            key=f"smtp_{smtp_label}",
            use_container_width=True,
        ):
            sc = SAMPLE_SCENARIOS[smtp_label]
            try:
                send_via_smtp(sc["sender"], sc["subject"], sc["body"])
                st.success("Sent via SMTP — will appear in queue shortly")
            except OSError as exc:
                st.error(f"SMTP failed: {exc}")

    st.markdown("---")
    st.subheader("Custom message")
    with st.form("ingest_form"):
        sender_in = st.text_input("From", "alex.rivera@example.com")
        subject_in = st.text_input("Subject", "Billing inquiry")
        body_in = st.text_area(
            "Body",
            "Hi support, my name is Alex Rivera. Account ID ACC-44012 was charged "
            "twice on card 4111-1111-1111-1111. Call me at +1-212-555-0142.",
            height=110,
        )
        submitted = st.form_submit_button("Triage →", use_container_width=True)

    if submitted:
        with st.spinner("Triaging…"):
            try:
                created = ingest_text(sender_in, subject_in, body_in)
                fetch_tickets.clear()
                st.session_state["selected"] = created["id"]
                st.sidebar.success(f"Created {created['id']}")
                st.rerun()
            except Exception as exc:
                st.sidebar.error(f"Ingest failed: {exc}")


# ── Auto-refreshing main panel ────────────────────────────────────────
@st.fragment(run_every="10s")
def inbox_panel() -> None:
    tickets = fetch_tickets()
    online = check_gateway()

    # Status + metrics row
    status_cls = "gw-online" if online else "gw-offline"
    status_lbl = "● Gateway online" if online else "● Gateway offline"
    st.markdown(
        f'<span class="gw-status {status_cls}">{status_lbl}</span>',
        unsafe_allow_html=True,
    )
    from collections import Counter
    high = sum(1 for t in tickets if t.get("urgency") == "High")
    total_pii = sum(t.get("token_count", 0) for t in tickets)
    ms_vals = [t["classification_ms"] for t in tickets if t.get("classification_ms")]
    avg_ms = sum(ms_vals) / len(ms_vals) if ms_vals else None
    cat_counts = Counter(t.get("category", "General") for t in tickets)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Open tickets", len(tickets))
    m2.metric("High urgency", high)
    m3.metric("PII tokens replaced", total_pii)
    m4.metric("Avg classification", f"{avg_ms:.0f} ms" if avg_ms else "—")

    if tickets:
        with st.expander("Category breakdown", expanded=False):
            st.markdown(
                category_bars_html(cat_counts, len(tickets)),
                unsafe_allow_html=True,
            )

    # Apply sidebar filters (values stored in session_state by widget keys)
    cat_sel = st.session_state.get("category_filter", "All")
    urg_sel = st.session_state.get("urgency_filter", ["High", "Medium", "Low"])
    filtered = [
        t for t in tickets
        if (cat_sel == "All" or t.get("category") == cat_sel)
        and t.get("urgency") in urg_sel
    ]

    # Auto-select first ticket when selection is not in filtered list
    sel_id = st.session_state.get("selected")
    if filtered and sel_id not in {t["id"] for t in filtered}:
        sel_id = filtered[0]["id"]
        st.session_state["selected"] = sel_id

    st.markdown("---")
    list_col, detail_col = st.columns([0.40, 0.60])

    # ── Queue ─────────────────────────────────────────────────────────
    with list_col:
        st.subheader(f"Queue ({len(filtered)})")
        if not filtered:
            st.info(
                "No tickets yet. Use the quick demo scenarios in the sidebar, "
                "or wait a moment for sample `.eml` files to load automatically."
            )

        for ticket in filtered:
            urgency = ticket.get("urgency", "Low")
            icon = URGENCY_ICON.get(urgency, "⚪")
            cat_label = ticket.get("category", "")
            subject_preview = ticket.get("subject", "")[:48]
            is_selected = ticket["id"] == sel_id
            ms = ticket.get("classification_ms")
            ms_label = f"{ms:.0f} ms" if ms is not None else "—"

            try:
                ts = datetime.fromisoformat(
                    ticket.get("created_at", "").replace("Z", "+00:00")
                ).strftime("%H:%M:%S")
            except ValueError:
                ts = ""

            with st.container(border=True):
                if is_selected:
                    st.markdown(
                        f"**{icon} {ticket['id']}** &nbsp;"
                        f'<span class="badge badge-{urgency}">{urgency}</span>'
                        f" &nbsp;<span style='color:#6A6E73;font-size:0.82rem'>"
                        f"{cat_label}</span>",
                        unsafe_allow_html=True,
                    )
                    st.caption(f"▶ {subject_preview}")
                else:
                    btn_label = (
                        f"{icon} {ticket['id']}  ·  {cat_label}  ·  {subject_preview}"
                    )
                    if st.button(
                        btn_label,
                        key=f"sel_{ticket['id']}",
                        use_container_width=True,
                    ):
                        st.session_state["selected"] = ticket["id"]
                        sel_id = ticket["id"]
                        st.rerun()
                st.caption(f"{ts} · {ms_label} classification")

    # ── Detail view ───────────────────────────────────────────────────
    selected = next((t for t in filtered if t["id"] == sel_id), None)

    with detail_col:
        if selected is None:
            st.subheader("Ticket detail")
            st.write("Select a ticket from the queue.")
        else:
            urgency = selected.get("urgency", "Low")
            ms_val = selected.get("classification_ms")
            ms_disp = f"{ms_val:.0f} ms" if ms_val is not None else "—"
            token_count = selected.get("token_count", 0)

            # Ticket ID + timestamp as subheader
            try:
                ts_full = datetime.fromisoformat(
                    selected.get("created_at", "").replace("Z", "+00:00")
                ).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                ts_full = selected.get("created_at", "")
            source = selected.get("source", "")
            st.subheader(selected["id"])
            st.caption(
                f"Received {ts_full}"
                + (f"  ·  via {source}" if source else "")
            )

            # AI classification metadata

            d1, d2, d3 = st.columns(3)
            d1.markdown(f"**Category** *(AI)*  \n{selected['category']}")
            d2.markdown(
                f"**Urgency** *(AI)*  \n"
                f'<span class="badge badge-{urgency}">{urgency}</span>',
                unsafe_allow_html=True,
            )
            d3.markdown(f"**SLA**  \n`{ms_disp}`")

            # Envelope fields — escape user-supplied strings before HTML injection
            sender_esc = html.escape(selected.get("sender", ""))
            subject_esc = html.escape(selected.get("subject", ""))
            st.markdown(
                f"**From:** {sender_esc} &nbsp;"
                f"**·** &nbsp; **Subject:** {subject_esc}",
                unsafe_allow_html=True,
            )
            st.markdown("---")

            # PII token badges — extracted from sanitized_text so the vault
            # endpoint is never hit before an agent explicitly opens the vault.
            sanitized_preview = selected.get("sanitized_text", "")
            vault_keys = sorted(set(re.findall(r"\[[A-Z_]+_\d+\]", sanitized_preview)))
            if vault_keys:
                badges = " ".join(
                    f'<span class="pii-token">{html.escape(k)}</span>'
                    for k in vault_keys
                )
                st.markdown(
                    f"**PII detected** &nbsp; {badges}",
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    "<span style='color:#6A6E73;font-size:0.85rem'>"
                    "No PII tokens detected in this message.</span>",
                    unsafe_allow_html=True,
                )

            # Sanitized body
            st.markdown("**Sanitized body** *(AI-generated)*")
            body_html = highlight_tokens(selected.get("sanitized_text", ""))
            st.markdown(
                f'<div class="sanitized-body">{body_html}</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                f"{token_count} PII token{'s' if token_count != 1 else ''} "
                "replaced · downstream queues receive only this payload."
            )

            # AI-generated one-line summary (RHAII output)
            summary = selected.get("summary", "")
            if summary:
                st.markdown("**AI summary** *(AI-generated)*")
                st.info(summary)

            # ── Downstream payload panel ──────────────────────────
            with st.expander(
                f"📤 What downstream systems see — `GET /tickets/{selected['id']}`",
                expanded=False,
            ):
                st.caption(
                    "This is the exact JSON any downstream consumer receives: "
                    "category, urgency, summary, and sanitized text with tokens. "
                    "No raw PII crosses this boundary. "
                    "The sender address is present as a routing key; "
                    "in an enterprise deployment it would map to a CRM record keyed by the ticket ID."
                )
                downstream_payload = {
                    "id": selected["id"],
                    "sender": selected.get("sender", ""),
                    "subject": selected.get("subject", ""),
                    "category": selected["category"],
                    "urgency": selected.get("urgency", ""),
                    "summary": selected.get("summary", ""),
                    "sanitized_text": selected.get("sanitized_text", ""),
                    "token_count": selected.get("token_count", 0),
                    "classification_ms": selected.get("classification_ms"),
                    "model": selected.get("model", ""),
                    "created_at": selected.get("created_at", ""),
                }
                st.code(
                    json.dumps(downstream_payload, indent=2, ensure_ascii=False),
                    language="json",
                )
                st.caption(
                    "`GET /tickets/{id}/vault` is a separate, gated endpoint — "
                    "it returns the original body and full token map only to authorized agents."
                )

            st.markdown("---")

            # ── Authorized rehydration ─────────────────────────────
            vault_key = f"vault_open_{selected['id']}"
            st.markdown(
                '<div class="vault-warning">'
                "<strong>Authorized rehydration.</strong> "
                "Original PII — including the sender's contact details — is stored server-side "
                "in a vault keyed by the ticket ID above. "
                "The sanitized body uses tokens (<code>[NAME_1]</code>, <code>[PHONE_1]</code>, …) "
                "rather than blanks, so authorized agents can recover the full context "
                "from the vault when they need to reply. "
                "Raw data must never appear in downstream cloud logs."
                "</div>",
                unsafe_allow_html=True,
            )

            if not st.session_state.get(vault_key, False):
                if st.button(
                    "🔓 View original PII vault",
                    key=f"btn_open_{selected['id']}",
                ):
                    st.session_state[vault_key] = True
                    st.rerun()
            else:
                vault_data = fetch_vault(selected["id"])
                col_close, _ = st.columns([0.35, 0.65])
                if col_close.button(
                    "🔒 Close vault", key=f"btn_close_{selected['id']}"
                ):
                    st.session_state[vault_key] = False
                    st.rerun()

                if vault_data is None:
                    st.error("Could not load vault for this ticket.")
                else:
                    mapping = vault_data.get("vault") or {}
                    v1, v2 = st.columns(2)
                    with v1:
                        st.markdown(
                            "**Original body** "
                            "<span style='color:#C9190B;font-size:0.78rem'>"
                            "⬤ raw PII</span>",
                            unsafe_allow_html=True,
                        )
                        orig_html = highlight_originals(
                            vault_data.get("original_text", ""), mapping
                        )
                        st.markdown(
                            f'<div class="sanitized-body">{orig_html}</div>',
                            unsafe_allow_html=True,
                        )
                    with v2:
                        st.markdown(
                            "**Sanitized body** "
                            "<span style='color:#0066CC;font-size:0.78rem'>"
                            "⬤ tokens only</span>",
                            unsafe_allow_html=True,
                        )
                        san_html = highlight_tokens(
                            selected.get("sanitized_text", "")
                        )
                        st.markdown(
                            f'<div class="sanitized-body">{san_html}</div>',
                            unsafe_allow_html=True,
                        )
                        st.markdown("**Token map**")
                        st.markdown(
                            token_table_html(mapping),
                            unsafe_allow_html=True,
                        )

                    original_sender = vault_data.get(
                        "original_sender", vault_data.get("sender", "")
                    )
                    if original_sender:
                        render_reply_actions(
                            reply_recipient(original_sender),
                            selected.get("subject", ""),
                        )
inbox_panel()
