import importlib
from unittest.mock import patch

import pytest

from app.email_parser import parse_raw_email
from app.inference import extract_json_object
from app.tokenizer import heuristic_triage, tokenize_structured_pii


SAMPLE = b"""From: Jane Martinez <jane.martinez@example.com>
To: support@example.com
Subject: Charged twice on my card
Date: Wed, 26 Aug 2026 09:15:00 -0400
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

Hi support, my card was charged twice. My account ID is ACC-998877
and my card is 4111-1111-1111-1111. Please call me at +1-212-555-0100.
My name is Jane Martinez.
"""


def test_parse_raw_email_extracts_headers_and_body():
    parsed = parse_raw_email(SAMPLE)
    assert parsed["sender"].startswith("Jane Martinez")
    assert "Charged twice" in parsed["subject"]
    assert "ACC-998877" in parsed["body"]


def test_tokenize_replaces_card_phone_account_and_name():
    parsed = parse_raw_email(SAMPLE)
    sanitized, vault = tokenize_structured_pii(parsed["body"])
    assert "4111" not in sanitized
    assert "+1-212-555-0100" not in sanitized
    assert "ACC-998877" not in sanitized
    assert "Jane Martinez" not in sanitized
    assert "[CARD_LAST4_1]" in sanitized
    assert "[PHONE_1]" in sanitized
    assert "[ACCOUNT_ID_1]" in sanitized
    assert "[NAME_1]" in sanitized
    assert vault.mapping["[PHONE_1]"] == "+1-212-555-0100"
    assert "Jane Martinez" in vault.mapping.values()
    # Card vault value must be last-4 mask only — never the full PAN.
    assert vault.mapping.get("[CARD_LAST4_1]", "").endswith("-1111")
    assert "4111111111111111" not in vault.mapping.values()


def test_locked_out_is_not_treated_as_a_name():
    sanitized, vault = tokenize_structured_pii(
        "I am locked out after MFA. My name is Priya Shah."
    )
    assert "locked out" in sanitized
    assert "[NAME_1]" in sanitized
    assert "Priya Shah" not in sanitized
    assert vault.mapping["[NAME_1]"] == "Priya Shah"


def test_heuristic_triage_billing_high():
    category, urgency = heuristic_triage(
        "Urgent: I was charged twice on my billing statement"
    )
    assert category == "Billing"
    assert urgency == "High"


def test_extract_json_object_from_fenced_block():
    payload = extract_json_object(
        '```json\n{"category": "Billing", "urgency": "High", "sanitized_text": "ok"}\n```'
    )
    assert payload["category"] == "Billing"
    assert payload["sanitized_text"] == "ok"


def test_normalize_maps_redacted_text():
    from app.inference import _normalize

    result = _normalize(
        {
            "category": "Billing",
            "urgency": "High",
            "redacted_text": "call [REDACTED]",
        },
        "fallback",
        "mock-triage",
    )
    assert result["sanitized_text"] == "call [REDACTED]"
    assert result["model"] == "mock-triage"
    assert "summary" in result


def test_gateway_parse_bytes_reads_plain_text():
    from gateways.email_classification_gateway import VLLMEmailGateway

    gateway = VLLMEmailGateway(
        {"base_url": "http://127.0.0.1:8000/v1", "classify_model": "mock-triage"}
    )
    gateway.parse_bytes(SAMPLE)
    types = [part.get_content_type() for part in gateway.message.walk()]
    assert "text/plain" in types


# ── Pipeline tests ────────────────────────────────────────────────────


def test_pipeline_rejects_model_pan(tmp_path, monkeypatch):
    """Merge must reject model output that reintroduces a Luhn-valid PAN."""
    monkeypatch.setenv("TICKET_DATA_DIR", str(tmp_path))

    import app.store as store_mod
    importlib.reload(store_mod)

    fake_result = {
        "category": "Billing",
        "urgency": "High",
        "sanitized_text": "model echoed the raw PAN 4111-1111-1111-1111 back",
        "summary": "Billing issue reported.",
        "model": "mock-triage",
    }
    with patch("app.pipeline.inference.classify_and_sanitize", return_value=fake_result):
        from app.pipeline import process_parsed_email

        ticket = process_parsed_email(
            sender="jane@example.com",
            subject="Billing issue",
            body="Card 4111-1111-1111-1111 was charged twice.",
            source="test",
        )

    # Full PAN must not appear in stored sanitized body.
    assert "4111-1111-1111-1111" not in ticket["sanitized_text"]
    # Model text must not have been used as-is.
    assert "model echoed" not in ticket["sanitized_text"]
    # Category and urgency still come from the model.
    assert ticket["category"] == "Billing"
    assert ticket["urgency"] == "High"


def test_pipeline_accepts_model_names(tmp_path, monkeypatch):
    """Model replacing an unstructured name gets recorded in the vault."""
    monkeypatch.setenv("TICKET_DATA_DIR", str(tmp_path))

    import app.store as store_mod
    importlib.reload(store_mod)

    # Body has a name the regex won't catch (no intro phrase, no signoff).
    body = "Hello, Alex Rivera wants a refund for ACC-12345."
    # After regex tokenization: ACC-12345 → [ACCOUNT_ID_1]; name stays raw.

    fake_result = {
        "category": "Billing",
        "urgency": "Low",
        "sanitized_text": "Hello, [NAME_1] wants a refund for [ACCOUNT_ID_1].",
        "summary": "Billing refund request received.",
        "model": "mock-triage",
    }

    with patch("app.pipeline.inference.classify_and_sanitize", return_value=fake_result):
        from app.pipeline import process_parsed_email

        ticket = process_parsed_email(
            sender="a@example.com",
            subject="Refund",
            body=body,
            source="test",
        )

    # Model output accepted: name token present, raw name absent.
    assert "[NAME_1]" in ticket["sanitized_text"]
    assert "[ACCOUNT_ID_1]" in ticket["sanitized_text"]
    assert "Alex Rivera" not in ticket["sanitized_text"]


def test_heuristic_fallback_uses_tokenized_text(tmp_path, monkeypatch):
    """When inference raises, fallback runs on regex-sanitized text, not raw body."""
    monkeypatch.setenv("TICKET_DATA_DIR", str(tmp_path))

    import app.store as store_mod
    importlib.reload(store_mod)

    with patch(
        "app.pipeline.inference.classify_and_sanitize",
        side_effect=RuntimeError("down"),
    ):
        from app.pipeline import process_parsed_email

        ticket = process_parsed_email(
            sender="user@example.com",
            subject="Charged twice",
            body="Card 4111-1111-1111-1111 was charged twice urgently.",
            source="test",
        )

    assert ticket["model"] == "heuristic-fallback"
    assert ticket["category"] == "Billing"
    assert ticket["urgency"] == "High"
    # Raw PAN must not appear in the stored body even on the fallback path.
    assert "4111-1111-1111-1111" not in ticket["sanitized_text"]


def test_pipeline_heuristic_fallback_on_inference_error(tmp_path, monkeypatch):
    """Alias kept for backward compatibility with previous test name."""
    test_heuristic_fallback_uses_tokenized_text(tmp_path, monkeypatch)


# ── Store tests ───────────────────────────────────────────────────────


def test_store_public_omits_vault_and_original(tmp_path, monkeypatch):
    """Public ticket view must not expose vault contents or original body."""
    monkeypatch.setenv("TICKET_DATA_DIR", str(tmp_path))

    import app.store as store_mod
    importlib.reload(store_mod)
    store_mod.load()

    ticket = store_mod.create_ticket(
        sender="a@b.com",
        subject="Test",
        original_text="raw body with 4111-1111-1111-1111",
        sanitized_text="sanitized body with [CARD_LAST4_1]",
        category="Billing",
        urgency="High",
        summary="Billing issue reported.",
        vault={"[CARD_LAST4_1]": "****-1111"},
        classification_ms=42.0,
        source="test",
        model="mock",
    )
    public = store_mod.get_ticket(ticket["id"])  # no include_vault

    assert "vault" not in public
    assert "original_text" not in public
    assert public["token_count"] == 1
    assert public["sanitized_text"] == "sanitized body with [CARD_LAST4_1]"
    assert public.get("summary") == "Billing issue reported."


def test_vault_requires_secret(tmp_path, monkeypatch):
    """GET /vault returns 401 without secret, 200 with correct X-Vault-Secret."""
    monkeypatch.setenv("TICKET_DATA_DIR", str(tmp_path))

    import app.store as store_mod
    importlib.reload(store_mod)
    store_mod.load()

    ticket = store_mod.create_ticket(
        sender="[EMAIL_1]",
        subject="test",
        original_text="raw",
        sanitized_text="safe [EMAIL_1]",
        category="General",
        urgency="Low",
        summary="",
        vault={"[EMAIL_1]": "a@b.com"},
        classification_ms=1.0,
        source="test",
        model="mock",
    )

    import app.main as main_mod
    from fastapi import HTTPException

    monkeypatch.setattr(main_mod, "VAULT_SECRET", "my-secret")
    monkeypatch.setattr(main_mod, "store", store_mod)

    # Wrong secret → 401
    with pytest.raises(HTTPException) as exc_info:
        main_mod.get_vault(ticket["id"], x_vault_secret="wrong")
    assert exc_info.value.status_code == 401

    # Correct secret → 200
    result = main_mod.get_vault(ticket["id"], x_vault_secret="my-secret")
    assert result["id"] == ticket["id"]
    assert "vault" in result
    assert "original_text" in result


def test_tokenize_shared_vault_deduplicates_across_fields():
    """Same value in sender and body should produce a single token."""
    _, vault = tokenize_structured_pii("jane@example.com")
    sanitized, vault = tokenize_structured_pii(
        "Contact jane@example.com for help.", vault=vault
    )
    assert sanitized.count("[EMAIL_1]") == 1
    assert len([k for k in vault.mapping if k.startswith("[EMAIL_")]) == 1


def test_tokenize_from_header_handles_display_name():
    """RFC-822 From header with a person display name produces NAME + EMAIL tokens."""
    from app.tokenizer import TokenVault, tokenize_from_header

    vault = TokenVault()
    result = tokenize_from_header("Jane Martinez <jane@example.com>", vault)
    assert "[NAME_1]" in result
    assert "[EMAIL_1]" in result
    assert vault.mapping["[NAME_1]"] == "Jane Martinez"
    assert vault.mapping["[EMAIL_1]"] == "jane@example.com"


def test_merge_model_sanitization_rejects_dropped_token():
    """merge_model_sanitization returns regex_text when a token is dropped."""
    from app.tokenizer import TokenVault, merge_model_sanitization

    vault = TokenVault()
    vault.mapping["[PHONE_1]"] = "+1-212-555-0100"
    vault._counts["PHONE"] = 1

    regex_text = "Call [PHONE_1] urgently."
    model_text = "Call (212) 555-0100 urgently."  # token dropped

    result = merge_model_sanitization(regex_text, model_text, vault)
    assert result == regex_text


def test_merge_model_sanitization_accepts_new_name_token():
    """merge_model_sanitization accepts model output with a new NAME token."""
    from app.tokenizer import TokenVault, merge_model_sanitization

    vault = TokenVault()
    vault.mapping["[ACCOUNT_ID_1]"] = "ACC-12345"
    vault._counts["ACCOUNT_ID"] = 1

    regex_text = "Alex Rivera requests refund for [ACCOUNT_ID_1]."
    model_text = "[NAME_1] requests refund for [ACCOUNT_ID_1]."

    result = merge_model_sanitization(regex_text, model_text, vault)
    assert result == model_text
    # Name token should be recorded in vault
    assert vault.mapping.get("[NAME_1]") == "Alex Rivera"


def test_merge_rejects_name_token_collision():
    """merge_model_sanitization rejects model output that reuses [NAME_1] for a
    different entity than the one already recorded in the vault."""
    from app.tokenizer import TokenVault, merge_model_sanitization

    vault = TokenVault()
    vault.mapping["[NAME_1]"] = "Jane Martinez"
    vault._counts["NAME"] = 1
    vault.mapping["[PHONE_1]"] = "+1-212-555-0100"
    vault._counts["PHONE"] = 1

    # regex_text still has Alex Rivera raw; model wrongly maps Alex to [NAME_1]
    regex_text = "Please refund Alex Rivera at [PHONE_1]."
    model_text = "Please refund [NAME_1] at [PHONE_1]."

    result = merge_model_sanitization(regex_text, model_text, vault)
    assert result == regex_text
    # Vault must not be corrupted — [NAME_1] stays Jane Martinez
    assert vault.mapping["[NAME_1]"] == "Jane Martinez"


def test_merge_accepts_continued_name_numbering():
    """merge_model_sanitization accepts model output where [NAME_2] is used for
    a new person while [NAME_1] already belongs to the sender."""
    from app.tokenizer import TokenVault, merge_model_sanitization

    vault = TokenVault()
    vault.mapping["[NAME_1]"] = "Jane Martinez"
    vault._counts["NAME"] = 1
    vault.mapping["[PHONE_1]"] = "+1-212-555-0100"
    vault._counts["PHONE"] = 1

    regex_text = "Please refund Alex Rivera at [PHONE_1]."
    model_text = "Please refund [NAME_2] at [PHONE_1]."

    result = merge_model_sanitization(regex_text, model_text, vault)
    assert result == model_text
    assert vault.mapping.get("[NAME_2]") == "Alex Rivera"


def test_pipeline_name_collision_with_from_header(tmp_path, monkeypatch):
    """Model using [NAME_1] for a body name when [NAME_1] is the sender must be
    rejected — vault [NAME_1] must remain the sender after merge."""
    monkeypatch.setenv("TICKET_DATA_DIR", str(tmp_path))

    import app.store as store_mod
    importlib.reload(store_mod)

    # Model incorrectly reuses [NAME_1] (Jane Martinez's token) for Alex Rivera
    fake_result = {
        "category": "Billing",
        "urgency": "Medium",
        "sanitized_text": "Please refund [NAME_1] on [ACCOUNT_ID_1].",
        "summary": "Billing refund request.",
        "model": "mock-triage",
    }
    with patch("app.pipeline.inference.classify_and_sanitize", return_value=fake_result):
        from app.pipeline import process_parsed_email

        ticket = process_parsed_email(
            sender="Jane Martinez <jane@example.com>",
            subject="Refund request",
            body="Please refund Alex Rivera on ACC-12345.",
            source="test",
        )

    # Merge must reject: [NAME_1] must not appear in sanitized body
    sanitized = ticket["sanitized_text"]
    assert "[NAME_1]" not in sanitized, "merge should have rejected the collision"
    # Alex Rivera is still raw (regex fallback used)
    assert "Alex Rivera" in sanitized
    # Vault [NAME_1] must still map to Jane Martinez
    full = store_mod.get_ticket(ticket["id"], include_vault=True)
    assert full["vault"].get("[NAME_1]") == "Jane Martinez"


def test_summary_sanitization_clears_raw_pan(tmp_path, monkeypatch):
    """Public ticket summary must be cleared when the model returns raw PII."""
    monkeypatch.setenv("TICKET_DATA_DIR", str(tmp_path))

    import app.store as store_mod
    importlib.reload(store_mod)

    fake_result = {
        "category": "Billing",
        "urgency": "High",
        "sanitized_text": "[CARD_LAST4_1] was charged twice.",
        "summary": (
            "Call Jane Martinez at +1-212-555-0100"
            " about 4111-1111-1111-1111"
        ),
        "model": "mock-triage",
    }
    with patch("app.pipeline.inference.classify_and_sanitize", return_value=fake_result):
        from app.pipeline import process_parsed_email

        ticket = process_parsed_email(
            sender="jane@example.com",
            subject="Billing",
            body="Card 4111-1111-1111-1111 was charged twice.",
            source="test",
        )

    assert "4111-1111-1111-1111" not in ticket.get("summary", "")
    assert ticket.get("summary", "") == ""
