"""End-to-end email triage: parse, tokenize, classify, persist."""

from __future__ import annotations

import logging
import time

from . import inference, store
from .email_parser import parse_raw_email
from .tokenizer import heuristic_triage, tokenize_structured_pii

logger = logging.getLogger(__name__)


def process_raw_email(raw_email_bytes: bytes, source: str = "smtp") -> dict:
    parsed = parse_raw_email(raw_email_bytes)
    return process_parsed_email(
        sender=parsed["sender"],
        subject=parsed["subject"],
        body=parsed["body"],
        source=source,
        raw_email_bytes=raw_email_bytes,
    )


def process_parsed_email(
    *,
    sender: str,
    subject: str,
    body: str,
    source: str,
    raw_email_bytes: bytes | None = None,
) -> dict:
    started = time.perf_counter()
    regex_sanitized, vault = tokenize_structured_pii(body)
    model_used = "heuristic-fallback"
    try:
        # Always send the regex-sanitized text to the model. This ensures the
        # mock (and real RHAIIS) echoes structured tokens ([NAME_1] etc.) in
        # sanitized_text rather than raw PII, regardless of ingestion path.
        result = inference.classify_and_sanitize(regex_sanitized)
        category = result["category"]
        urgency = result["urgency"]
        sanitized_text = result["sanitized_text"] or regex_sanitized
        model_used = result["model"]
    except Exception as exc:  # noqa: BLE001 — demo path must keep ingesting
        logger.warning("Inference failed (%s); using heuristic triage", exc)
        category, urgency = heuristic_triage(f"{subject}\n{body}")
        sanitized_text = regex_sanitized

    elapsed_ms = (time.perf_counter() - started) * 1000
    ticket = store.create_ticket(
        sender=sender,
        subject=subject,
        original_text=body,
        sanitized_text=sanitized_text,
        category=category,
        urgency=urgency,
        vault=vault.mapping,
        classification_ms=elapsed_ms,
        source=source,
        model=model_used,
    )
    return store.get_ticket(ticket["id"]) or ticket
