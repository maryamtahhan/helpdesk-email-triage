"""End-to-end email triage: parse, tokenize, classify, persist."""

from __future__ import annotations

import logging
import time

from . import inference, store
from .email_parser import parse_raw_email
from .tokenizer import (
    TokenVault,
    heuristic_triage,
    merge_model_sanitization,
    sanitize_model_summary,
    tokenize_from_header,
    tokenize_structured_pii,
)

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
    original_sender = sender

    # Shared vault so the same value in different fields gets the same token.
    # tokenize_from_header handles RFC-822 "Display Name <addr>" format and
    # mutates the vault in place.
    vault = TokenVault()
    regex_sanitized_sender = tokenize_from_header(sender, vault)
    regex_sanitized_subject, vault = tokenize_structured_pii(subject, vault=vault)
    regex_sanitized, vault = tokenize_structured_pii(body, vault=vault)

    model_used = "heuristic-fallback"
    summary = ""
    try:
        # Pass only the regex-sanitized body — RHAII never sees raw PII.
        result = inference.classify_and_sanitize(regex_sanitized)
        category = result["category"]
        urgency = result["urgency"]
        summary = sanitize_model_summary(result.get("summary", ""), vault)
        model_used = result["model"]
        # Merge: use RHAII sanitized_text (which may contain residual name tokens)
        # only if it passes all safety checks. Category and urgency always come
        # from the model; sanitized_text falls back to regex_text on failure.
        sanitized_text = merge_model_sanitization(
            regex_sanitized,
            result.get("sanitized_text", regex_sanitized),
            vault,
        )
    except Exception as exc:
        logger.warning("Inference failed (%s); using heuristic triage", exc)
        # Fallback operates on already-tokenized text so no raw PII is exposed.
        category, urgency = heuristic_triage(
            f"{regex_sanitized_subject}\n{regex_sanitized}"
        )
        sanitized_text = regex_sanitized

    elapsed_ms = (time.perf_counter() - started) * 1000
    ticket = store.create_ticket(
        sender=regex_sanitized_sender,
        subject=regex_sanitized_subject,
        original_text=body,
        original_sender=original_sender,
        sanitized_text=sanitized_text,
        summary=summary,
        category=category,
        urgency=urgency,
        vault=vault.mapping,
        classification_ms=elapsed_ms,
        source=source,
        model=model_used,
    )
    return store.get_ticket(ticket["id"]) or ticket
