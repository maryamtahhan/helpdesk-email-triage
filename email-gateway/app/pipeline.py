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
    # Tokenize all three user-supplied fields through a shared vault so tokens
    # are consistent (e.g. the same email address in the From header and body
    # gets the same [EMAIL_1] token) and the public view exposes no raw PII.
    regex_sanitized_sender, vault = tokenize_structured_pii(sender)
    regex_sanitized_subject, vault = tokenize_structured_pii(subject, vault=vault)
    regex_sanitized, vault = tokenize_structured_pii(body, vault=vault)
    model_used = "heuristic-fallback"
    try:
        # Always send the regex-sanitized text to the model so it never sees
        # raw PII. Only category and urgency are taken from the model response;
        # the regex-sanitized body is always what gets stored and displayed.
        # Using model sanitized_text as the display body is unsafe: a 1.5B
        # model can echo raw PII, drop existing tokens, or invent tokens that
        # have no entry in the vault.
        result = inference.classify_and_sanitize(regex_sanitized)
        category = result["category"]
        urgency = result["urgency"]
        sanitized_text = regex_sanitized
        model_used = result["model"]
    except Exception as exc:  # noqa: BLE001 — demo path must keep ingesting
        logger.warning("Inference failed (%s); using heuristic triage", exc)
        category, urgency = heuristic_triage(f"{subject}\n{body}")
        sanitized_text = regex_sanitized

    elapsed_ms = (time.perf_counter() - started) * 1000
    ticket = store.create_ticket(
        sender=regex_sanitized_sender,
        subject=regex_sanitized_subject,
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
