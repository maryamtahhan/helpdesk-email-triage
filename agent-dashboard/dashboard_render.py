"""HTML/CSS rendering helpers for the Streamlit agent inbox."""

from __future__ import annotations

import html
import json
import re

import streamlit.components.v1 as components
from dashboard_api import gmail_compose_url, mailto_reply_url, reply_subject

PAGE_CSS = """
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


def render_reply_actions(recipient: str, subject: str) -> None:
    """Offer mailto, Gmail web compose, and copy — Chrome often ignores mailto:."""
    subj = reply_subject(subject)
    mailto = mailto_reply_url(recipient, subject)
    gmail = gmail_compose_url(recipient, subject)
    components.html(
        f"""
        <div style="font-family: 'Source Sans Pro', sans-serif; margin-top: 0.75rem;">
          <p style="margin: 0 0 0.6rem; color: #6a6e73; font-size: 0.85rem;">
            Reply to <strong style="color:#151515">{html.escape(recipient)}</strong>
            · subject <em>{html.escape(subj)}</em>
          </p>
          <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
            <button id="gmail-btn" style="
              background:#0066CC;color:#fff;border:none;border-radius:0.25rem;
              padding:0.45rem 0.9rem;font-size:0.9rem;cursor:pointer;">
              Open in Gmail
            </button>
            <button id="mailto-btn" style="
              background:#f0f0f0;color:#151515;border:1px solid #d2d2d2;border-radius:0.25rem;
              padding:0.45rem 0.9rem;font-size:0.9rem;cursor:pointer;">
              Open mail app
            </button>
            <button id="copy-btn" style="
              background:#f0f0f0;color:#151515;border:1px solid #d2d2d2;border-radius:0.25rem;
              padding:0.45rem 0.9rem;font-size:0.9rem;cursor:pointer;">
              Copy address
            </button>
          </div>
          <p style="margin:0.5rem 0 0;color:#6a6e73;font-size:0.78rem;">
            In Chrome, use <strong>Open in Gmail</strong> (no mail app required).
            <code>mailto:</code> only works if Chrome has a handler at
            <code>chrome://settings/handlers</code>.
          </p>
          <script>
            const mailto = {json.dumps(mailto)};
            const gmail = {json.dumps(gmail)};
            const addr = {json.dumps(recipient)};
            document.getElementById('gmail-btn').onclick = () => {{
              window.open(gmail, '_blank', 'noopener,noreferrer');
            }};
            document.getElementById('mailto-btn').onclick = () => {{
              const topWin = window.top || window.parent || window;
              topWin.location.href = mailto;
            }};
            document.getElementById('copy-btn').onclick = async () => {{
              const btn = document.getElementById('copy-btn');
              try {{
                await navigator.clipboard.writeText(addr);
                btn.textContent = 'Copied!';
                setTimeout(() => {{ btn.textContent = 'Copy address'; }}, 2000);
              }} catch (e) {{
                window.prompt('Copy email address:', addr);
              }}
            }};
          </script>
        </div>
        """,
        height=145,
    )


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
