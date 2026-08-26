"""Support agent inbox for tokenized, AI-triaged helpdesk email."""

from __future__ import annotations

import html
import os
import pathlib
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
import streamlit as st

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/")
SMTP_HOST = os.environ.get("SMTP_HOST", "127.0.0.1")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "3025"))

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

# Quick-triage scenarios — bypass the file watcher, always available instantly
SAMPLE_SCENARIOS = {
    "💳 Double charge": {
        "sender": "jane.martinez@example.com",
        "subject": "Charged twice on my card",
        "body": (
            "Hi support, my name is Jane Martinez. My account ID is ACC-998877 "
            "and I was charged twice on card 4111-1111-1111-1111. "
            "Please call me at +1-212-555-0100 to resolve this urgently."
        ),
    },
    "🔒 MFA lockout": {
        "sender": "priya.shah@example.com",
        "subject": "Locked out after MFA reset",
        "body": (
            "I'm Priya Shah and I cannot log in after my MFA was reset. "
            "Account ID ACC-44012, SSN 000-00-0000 on file. "
            "Please call +1-212-555-0199."
        ),
    },
    "📶 VPN failure": {
        "sender": "sam.okonkwo@example.com",
        "subject": "VPN drops every 10 minutes",
        "body": (
            "This is Sam Okonkwo (sam.okonkwo@example.com). "
            "Our corporate VPN disconnects every 10 minutes since last night's patch. "
            "Call +1-212-555-0133. Urgent — blocking the entire team."
        ),
    },
    "💬 General thanks": {
        "sender": "jordan.lee@example.com",
        "subject": "Thanks for last week's webinar",
        "body": (
            "Hi, this is Jordan Lee. No action needed — just wanted to say "
            "the webinar last Tuesday was great and was provided without charge. "
            "Really appreciated it!"
        ),
    },
    "🏥 Healthcare billing": {
        "sender": "sarah.johnson@patient.example.com",
        "subject": "Question about my ER visit bill",
        "body": (
            "Hello, I'm Sarah Johnson. I received an unexpected invoice for my "
            "emergency room visit. My SSN on file is 000-00-0003 and my patient "
            "account is ACC-771234. The billed amount doesn't match what my "
            "insurer told me. Please contact me at +1-617-555-0177 to clarify."
        ),
    },
    "💼 HR payroll issue": {
        "sender": "marcus.chen@employee.example.com",
        "subject": "Payroll discrepancy — missing overtime",
        "body": (
            "I'm Marcus Chen (marcus.chen@employee.example.com). My employee "
            "account ACC-33401 was not credited for 12 hours of overtime last "
            "pay period. My SSN on file is 000-00-0004. "
            "Please call me at +1-415-555-0218 urgently."
        ),
    },
    "⚖️ GDPR deletion": {
        "sender": "emma.thornton@example.com",
        "subject": "GDPR right-to-erasure request",
        "body": (
            "I am Emma Thornton. I am exercising my right to erasure under GDPR "
            "Article 17. Please delete all personal data for account ACC-55601. "
            "Confirm to emma.thornton@example.com or call +1-312-555-0244. "
            "You have 30 days to comply."
        ),
    },
}

_PAGE_CSS = """
<style>
  .block-container { padding-top: 1rem; }

  /* ── AI disclaimer ──────────────────────────────────── */
  .ai-banner {
    background: #fff8f7;
    color: #1a1a1a;
    border-left: 4px solid #C9190B;
    border-radius: 0 4px 4px 0;
    padding: 0.55rem 1rem;
    margin-bottom: 0.8rem;
    font-size: 0.84rem;
  }

  /* ── Urgency badge ──────────────────────────────────── */
  .badge {
    display: inline-block;
    font-size: 0.68rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 10px;
    text-transform: uppercase;
    letter-spacing: 0.4px;
    vertical-align: middle;
  }
  .badge-High   { background: #C9190B; color: #fff; }
  .badge-Medium { background: #F0AB00; color: #000; }
  .badge-Low    { background: #3E8635; color: #fff; }

  /* ── PII token highlight ────────────────────────────── */
  .pii-token {
    background: #e7f1ff;
    color: #0066CC;
    border: 1px solid #bee1f4;
    border-radius: 3px;
    padding: 1px 5px;
    font-family: monospace;
    font-size: 0.87em;
    font-weight: 600;
    white-space: nowrap;
  }

  /* ── Sanitized body block ───────────────────────────── */
  .sanitized-body {
    background: #fafafa;
    color: #1a1a1a;
    border: 1px solid #e0e0e0;
    border-radius: 4px;
    padding: 0.75rem 0.9rem;
    font-size: 0.9rem;
    line-height: 1.65;
    white-space: pre-wrap;
    word-break: break-word;
  }

  /* ── Token map table ────────────────────────────────── */
  .token-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.83rem;
    margin-top: 0.2rem;
  }
  .token-table thead tr { background: #f0f0f0; }
  .token-table th {
    padding: 5px 9px;
    text-align: left;
    font-weight: 600;
    border-bottom: 2px solid #d2d2d2;
  }
  .token-table td {
    padding: 4px 9px;
    border-bottom: 1px solid #eee;
    vertical-align: top;
    word-break: break-all;
  }
  .token-table tr:last-child td { border-bottom: none; }
  .token-table tr:hover td { background: #f5f5f5; }
  .token-key {
    font-family: monospace;
    color: #0066CC;
    font-weight: 600;
    white-space: nowrap;
  }

  /* ── Gateway status pill ────────────────────────────── */
  .gw-status {
    font-size: 0.78rem;
    padding: 3px 9px;
    border-radius: 10px;
    display: inline-block;
    font-weight: 500;
  }
  .gw-online  { background: #e8f9e8; color: #1a6b1a; border: 1px solid #3E8635; }
  .gw-offline { background: #fde8e8; color: #a10000; border: 1px solid #C9190B; }

  /* ── PII original value highlight (vault before/after) ─ */
  .pii-original {
    background: #fdf3f2;
    color: #C9190B;
    border: 1px solid #f9b8b1;
    border-radius: 3px;
    padding: 1px 5px;
    font-weight: 600;
    white-space: nowrap;
  }

  /* ── Category distribution bars ─────────────────────── */
  .cat-bar-row {
    display: flex;
    align-items: center;
    margin-bottom: 5px;
    font-size: 0.8rem;
  }
  .cat-bar-label { width: 108px; color: #333; white-space: nowrap; }
  .cat-bar-track {
    flex: 1;
    background: #ebebeb;
    border-radius: 3px;
    height: 13px;
    margin: 0 8px;
  }
  .cat-bar-fill { border-radius: 3px; height: 13px; }
  .cat-bar-count { width: 20px; text-align: right; color: #6A6E73; }

  /* ── Vault button ───────────────────────────────────── */
  .vault-warning {
    background: #fff8e6;
    color: #1a1a1a;
    border-left: 4px solid #F0AB00;
    border-radius: 0 4px 4px 0;
    padding: 0.5rem 0.9rem;
    font-size: 0.83rem;
    margin-bottom: 0.6rem;
  }

  /* ── Sidebar scenario buttons ───────────────────────── */
  div[data-testid="stSidebarContent"] .stButton button {
    text-align: left;
    justify-content: flex-start;
  }
</style>
"""

st.set_page_config(
    page_title="Helpdesk triage inbox",
    page_icon="🎫",
    layout="wide",
)
st.markdown(_PAGE_CSS, unsafe_allow_html=True)

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
2. **Regex tokenization** — high-confidence PII (card numbers, phone numbers, SSNs, email addresses, account IDs, names) is immediately replaced with structured tokens: `[NAME_1]`, `[CARD_LAST4_1]`, `[PHONE_1]`, etc.  The originals go into a private vault keyed by ticket ID.
3. **AI classification** — the tokenized body is sent to Red Hat AI Inference 3.5 (vLLM on CPU, or the local mock) which returns `category` and `urgency` as structured JSON.
4. **Ticket created** — the sanitized body + AI labels appear in the queue. Downstream systems only ever see the tokenized text.

---

#### Navigating the UI

| Area | What it does |
|---|---|
| **Queue (left column)** | Filtered list of tickets, newest first.  Click a ticket to open it. |
| **Ticket detail (right column)** | Shows category, urgency, SLA ms, and the sanitized body with PII tokens highlighted in blue. |
| **Authorized rehydration** | Click **🔓 View original PII vault** to see original body (PII highlighted red) vs sanitized body (tokens in blue) side by side. Click 🔒 to close. State resets when you switch tickets. |
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


# ── Data helpers ──────────────────────────────────────────────────────
def check_gateway() -> bool:
    try:
        httpx.get(f"{GATEWAY_URL}/health", timeout=2.0).raise_for_status()
        return True
    except Exception:
        return False


@st.cache_data(ttl=3)
def fetch_tickets() -> list[dict]:
    try:
        r = httpx.get(f"{GATEWAY_URL}/tickets", timeout=10.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return []


@st.cache_data(ttl=10)
def fetch_vault(ticket_id: str) -> dict | None:
    try:
        r = httpx.get(f"{GATEWAY_URL}/tickets/{ticket_id}/vault", timeout=10.0)
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return None


def ingest_text(sender: str, subject: str, body: str) -> dict:
    r = httpx.post(
        f"{GATEWAY_URL}/ingest/raw",
        json={"sender": sender, "subject": subject, "body": body},
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json()


def send_via_smtp(sender: str, subject: str, body: str) -> None:
    """Send an email to the SMTP listener on port 3025."""
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = "support@helpdesk.local"
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5) as s:
        s.sendmail(sender, ["support@helpdesk.local"], msg.as_string())


def highlight_tokens(text: str) -> str:
    """HTML-escape text then wrap [TOKEN_N] patterns in a highlight span."""
    escaped = html.escape(text)
    return re.sub(
        r"(\[[A-Z_]+_\d+\])",
        r'<span class="pii-token">\1</span>',
        escaped,
    )


def highlight_originals(original_text: str, mapping: dict) -> str:
    """HTML-escape original body then highlight each raw PII value in red."""
    escaped = html.escape(original_text)
    # Sort longest-value-first to avoid partial-match replacements
    for _token, value in sorted(mapping.items(), key=lambda x: -len(x[1])):
        esc_val = html.escape(value)
        escaped = escaped.replace(
            esc_val,
            f'<span class="pii-original">{esc_val}</span>',
        )
    return escaped


def category_bars_html(cat_counts: dict, total: int) -> str:
    """Compact horizontal bar chart for category distribution."""
    if not total:
        return ""
    colors = {
        "Billing": "#C9190B",
        "Account Access": "#F0AB00",
        "Tech Support": "#0066CC",
        "General": "#3E8635",
    }
    rows = []
    for cat in ("Billing", "Account Access", "Tech Support", "General"):
        count = cat_counts.get(cat, 0)
        pct = count / total * 100
        color = colors.get(cat, "#6A6E73")
        rows.append(
            f'<div class="cat-bar-row">'
            f'<span class="cat-bar-label">{cat}</span>'
            f'<div class="cat-bar-track">'
            f'<div class="cat-bar-fill" style="width:{pct:.0f}%;background:{color}"></div>'
            f'</div>'
            f'<span class="cat-bar-count">{count}</span>'
            f'</div>'
        )
    return "".join(rows)


def token_table_html(mapping: dict) -> str:
    if not mapping:
        return "<em style='color:#6A6E73'>No tokens recorded.</em>"
    rows = "".join(
        f'<tr><td class="token-key">{html.escape(tok)}</td>'
        f"<td>{html.escape(val)}</td></tr>"
        for tok, val in mapping.items()
    )
    return (
        '<table class="token-table"><thead>'
        "<tr><th>Token</th><th>Original value</th></tr>"
        f"</thead><tbody>{rows}</tbody></table>"
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

            # Envelope fields
            st.markdown(
                f"**From:** {selected.get('sender', '')} &nbsp;"
                f"**·** &nbsp; **Subject:** {selected.get('subject', '')}",
                unsafe_allow_html=True,
            )
            st.markdown("---")

            # PII token badges — visible before vault, no values exposed
            vault_keys = list(
                (fetch_vault(selected["id"]) or {}).get("vault", {}).keys()
            ) if token_count > 0 else []
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

            st.markdown("---")

            # ── Authorized rehydration ─────────────────────────────
            vault_key = f"vault_open_{selected['id']}"
            st.markdown(
                '<div class="vault-warning">'
                "<strong>Authorized rehydration.</strong> "
                "Original PII is stored server-side in a vault keyed by ticket ID. "
                "Only authorized agents should access it — "
                "raw data must never appear in downstream cloud logs."
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


inbox_panel()
