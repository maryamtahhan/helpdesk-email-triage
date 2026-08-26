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


def test_gateway_parse_bytes_reads_plain_text():
    from gateways.email_classification_gateway import VLLMEmailGateway

    gateway = VLLMEmailGateway(
        {"base_url": "http://127.0.0.1:8000/v1", "classify_model": "mock-triage"}
    )
    gateway.parse_bytes(SAMPLE)
    types = [part.get_content_type() for part in gateway.message.walk()]
    assert "text/plain" in types
