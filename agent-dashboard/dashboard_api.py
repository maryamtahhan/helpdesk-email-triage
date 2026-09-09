"""HTTP and SMTP helpers for the Streamlit agent inbox."""

from __future__ import annotations

import os
import re
import smtplib
import urllib.parse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
import streamlit as st

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/")
SMTP_HOST = os.environ.get("SMTP_HOST", "127.0.0.1")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "3025"))
VAULT_SECRET = os.environ.get("VAULT_SECRET", "")
INGEST_API_KEY = os.environ.get("INGEST_API_KEY", "")


def _gateway_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if INGEST_API_KEY:
        headers["X-Ingest-Key"] = INGEST_API_KEY
    return headers


def check_gateway() -> bool:
    try:
        httpx.get(f"{GATEWAY_URL}/health", timeout=2.0).raise_for_status()
        return True
    except Exception:
        return False


@st.cache_data(ttl=3)
def fetch_tickets() -> list[dict]:
    try:
        response = httpx.get(
            f"{GATEWAY_URL}/tickets",
            headers=_gateway_headers(),
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError:
        return []


@st.cache_data(ttl=10)
def fetch_vault(ticket_id: str) -> dict | None:
    headers = _gateway_headers()
    if VAULT_SECRET:
        headers["X-Vault-Secret"] = VAULT_SECRET
    try:
        response = httpx.get(
            f"{GATEWAY_URL}/tickets/{ticket_id}/vault",
            headers=headers,
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError:
        return None


def ingest_text(sender: str, subject: str, body: str) -> dict:
    response = httpx.post(
        f"{GATEWAY_URL}/ingest/raw",
        json={"sender": sender, "subject": subject, "body": body},
        headers=_gateway_headers(),
        timeout=120.0,
    )
    response.raise_for_status()
    return response.json()


def send_via_smtp(sender: str, subject: str, body: str) -> None:
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = "support@helpdesk.local"
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5) as smtp:
        smtp.sendmail(sender, ["support@helpdesk.local"], msg.as_string())


def reply_recipient(original_sender: str) -> str:
    match = re.search(r"<([^>]+)>", original_sender)
    return match.group(1) if match else original_sender.strip()


def reply_subject(subject: str) -> str:
    return subject if re.match(r"^re:\s", subject, re.I) else f"Re: {subject}"


def mailto_reply_url(recipient: str, subject: str) -> str:
    subj = reply_subject(subject)
    return f"mailto:{recipient}?{urllib.parse.urlencode({'subject': subj})}"


def gmail_compose_url(recipient: str, subject: str) -> str:
    subj = reply_subject(subject)
    params = urllib.parse.urlencode(
        {"view": "cm", "fs": "1", "to": recipient, "su": subj}
    )
    return f"https://mail.google.com/mail/?{params}"
