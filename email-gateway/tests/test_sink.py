import hashlib
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.sink import dispatch, parse_sinks, post_webhook, sign_payload, webhook_urls
from app.triage_result import TriageResult


def _sample_result() -> TriageResult:
    return TriageResult(
        id="TICKET-9001",
        sender="[EMAIL_1]",
        subject="VPN drops",
        sanitized_text="My VPN drops every 10 minutes.",
        summary="Customer reports VPN instability.",
        category="Tech Support",
        urgency="High",
        classification_ms=42.5,
        source="test",
        model="mock-triage",
        created_at="2026-08-27T18:00:00+00:00",
        token_count=2,
    )


def test_triage_result_from_ticket_ignores_vault_fields():
    ticket = {
        "id": "TICKET-9001",
        "sender": "[EMAIL_1]",
        "subject": "Billing",
        "sanitized_text": "Charge on [CARD_LAST4_1]",
        "summary": "Billing dispute",
        "category": "Billing",
        "urgency": "High",
        "classification_ms": 10.0,
        "source": "smtp",
        "model": "mock-triage",
        "created_at": "2026-08-27T18:00:00+00:00",
        "original_text": "secret body",
        "original_sender": "jane@example.com",
        "vault": {"[EMAIL_1]": "jane@example.com"},
    }
    result = TriageResult.from_ticket(ticket)
    payload = result.to_dict()
    assert payload["token_count"] == 1
    assert "original_text" not in payload
    assert "vault" not in payload
    assert "original_sender" not in payload


def test_triage_result_rejects_extra_fields():
    with pytest.raises(Exception):
        TriageResult.from_public_dict(
            {
                "id": "TICKET-9001",
                "sender": "[EMAIL_1]",
                "subject": "x",
                "sanitized_text": "x",
                "category": "General",
                "urgency": "Low",
                "classification_ms": 1.0,
                "source": "test",
                "model": "mock",
                "created_at": "2026-08-27T18:00:00+00:00",
                "token_count": 0,
                "vault": {"[EMAIL_1]": "secret@example.com"},
            }
        )


def test_parse_sinks_and_webhook_urls():
    sinks = parse_sinks("log, webhook:https://example.com/hook ,webhook:https://b.example/h")
    assert sinks == ["log", "webhook:https://example.com/hook", "webhook:https://b.example/h"]
    assert webhook_urls(sinks) == [
        "https://example.com/hook",
        "https://b.example/h",
    ]


def test_sign_payload_hmac():
    body = b'{"id":"TICKET-9001"}'
    expected = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert sign_payload(body, "secret") == f"sha256={expected}"


class _WebhookHandler(BaseHTTPRequestHandler):
    received: list[tuple[dict[str, str], bytes]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        headers = {k: v for k, v in self.headers.items()}
        self.__class__.received.append((headers, body))
        self.send_response(200)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return


def test_post_webhook_delivers_public_payload(tmp_path, monkeypatch):
    _WebhookHandler.received.clear()
    server = HTTPServer(("127.0.0.1", 0), _WebhookHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    result = _sample_result()
    secret = "hook-secret"
    monkeypatch.setenv("TICKET_SINK_SECRET", secret)

    try:
        post_webhook(f"http://127.0.0.1:{port}/hook", result, secret=secret, retries=1)
    finally:
        server.shutdown()

    assert len(_WebhookHandler.received) == 1
    headers, body = _WebhookHandler.received[0]
    payload = json.loads(body.decode())
    assert payload["id"] == "TICKET-9001"
    assert "vault" not in payload
    assert headers["X-Ticket-Signature"] == sign_payload(body, secret)


def test_pipeline_dispatches_webhook(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TICKET_SINK_SYNC", "1")

    _WebhookHandler.received.clear()
    server = HTTPServer(("127.0.0.1", 0), _WebhookHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("TICKET_SINK", f"webhook:http://127.0.0.1:{port}/hook")

    import importlib

    import app.store as store_mod

    importlib.reload(store_mod)

    from unittest.mock import patch

    from app.pipeline import process_parsed_email

    fake_result = {
        "category": "Tech Support",
        "urgency": "High",
        "sanitized_text": "VPN issue for [NAME_1]",
        "summary": "VPN drops frequently.",
        "model": "mock-triage",
    }

    try:
        with patch("app.pipeline.inference.classify_and_sanitize", return_value=fake_result):
            public = process_parsed_email(
                sender="Sam Okonkwo <sam.okonkwo@example.com>",
                subject="VPN drops every 10 minutes",
                body="My VPN drops. My name is Sam Okonkwo.",
                source="test-webhook",
            )
    finally:
        server.shutdown()

    assert public["category"] == "Tech Support"
    assert len(_WebhookHandler.received) == 1
    _, body = _WebhookHandler.received[0]
    webhook_payload = json.loads(body.decode())
    assert webhook_payload["id"] == public["id"]
    assert webhook_payload == public
    assert "vault" not in webhook_payload
    assert "sam.okonkwo@example.com" not in body.decode()


def test_dispatch_log_sink(monkeypatch, caplog):
    monkeypatch.setenv("TICKET_SINK", "log")
    monkeypatch.setenv("TICKET_SINK_SYNC", "1")
    import logging

    caplog.set_level(logging.INFO)
    dispatch(_sample_result(), sync=True)
    assert any("TriageResult" in record.message for record in caplog.records)
