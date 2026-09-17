#!/usr/bin/env python3
"""Probe that the dashboard serves the static welcome page (not Streamlit-only UI)."""
from __future__ import annotations

import os
import ssl
import sys
import urllib.error
import urllib.request

MARKERS = ("You're connected", "You\u2019re connected", "Open the inbox")
STREAMLIT_INBOX = "Helpdesk triage inbox"


def check_welcome(body: str) -> bool:
    if STREAMLIT_INBOX in body:
        return False
    return any(m in body for m in MARKERS)


def fetch(url: str) -> str:
    ctx = None
    if url.startswith("https:"):
        ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(url, timeout=10, context=ctx) as resp:
        if resp.status != 200:
            raise urllib.error.URLError(f"HTTP {resp.status}")
        return resp.read().decode("utf-8", errors="replace")


def main() -> int:
    url = (
        os.environ.get("WELCOME_PROBE_URL")
        or (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8501/welcome")
    )
    try:
        body = fetch(url)
    except (urllib.error.URLError, OSError, TimeoutError):
        return 1
    return 0 if check_welcome(body) else 1


if __name__ == "__main__":
    sys.exit(main())
