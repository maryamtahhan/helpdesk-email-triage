"""Dispatch TriageResult payloads to optional downstream sinks."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time

import httpx

from .triage_result import TriageResult

logger = logging.getLogger(__name__)

_WEBHOOK_PREFIX = "webhook:"
_DEFAULT_RETRIES = 3


def parse_sinks(raw: str | None = None) -> list[str]:
    value = raw if raw is not None else os.environ.get("TICKET_SINK", "")
    return [part.strip() for part in value.split(",") if part.strip()]


def webhook_urls(sinks: list[str]) -> list[str]:
    return [entry[len(_WEBHOOK_PREFIX) :] for entry in sinks if entry.startswith(_WEBHOOK_PREFIX)]


def sign_payload(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def post_webhook(
    url: str,
    result: TriageResult,
    *,
    secret: str = "",
    retries: int = _DEFAULT_RETRIES,
) -> None:
    body = json.dumps(result.to_dict(), ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Ticket-Signature"] = sign_payload(body, secret)

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = httpx.post(url, content=body, headers=headers, timeout=10.0)
            response.raise_for_status()
            logger.info("Webhook delivered %s to %s", result.id, url)
            return
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Webhook attempt %d/%d failed for %s → %s: %s",
                attempt + 1,
                retries,
                result.id,
                url,
                exc,
            )
            if attempt < retries - 1:
                time.sleep(0.5 * (2**attempt))

    if last_error is not None:
        logger.error(
            "Webhook delivery exhausted retries for %s → %s: %s",
            result.id,
            url,
            last_error,
        )


def dispatch(result: TriageResult, *, sync: bool = False) -> None:
    """Send the public triage payload to configured sinks."""
    sinks = parse_sinks()
    if not sinks:
        return

    secret = os.environ.get("TICKET_SINK_SECRET", "")

    def _run() -> None:
        if "log" in sinks:
            logger.info("TriageResult %s", json.dumps(result.to_dict(), ensure_ascii=False))

        for url in webhook_urls(sinks):
            post_webhook(url, result, secret=secret)

    if sync or os.environ.get("TICKET_SINK_SYNC", "").lower() in {"1", "true", "yes"}:
        _run()
        return

    thread = threading.Thread(
        target=_run,
        daemon=True,
        name=f"ticket-sink-{result.id}",
    )
    thread.start()
