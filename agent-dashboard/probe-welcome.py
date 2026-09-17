#!/usr/bin/env python3
"""Kubernetes probe: nginx must serve the static welcome page (not Streamlit-only UI)."""
from __future__ import annotations

import sys
import urllib.error
import urllib.request

MARKERS = ("You're connected", "You\u2019re connected", "Open the inbox")


def main() -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8501/welcome", timeout=5) as resp:
            if resp.status != 200:
                return 1
            body = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, TimeoutError):
        return 1
    if "Helpdesk triage inbox" in body:
        return 1
    return 0 if any(m in body for m in MARKERS) else 1


if __name__ == "__main__":
    sys.exit(main())
