import importlib
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GATEWAY_MODE", "API_ONLY")

    import app.store as store_mod

    importlib.reload(store_mod)

    import app.main as main_mod

    importlib.reload(main_mod)
    monkeypatch.setattr(main_mod, "store", store_mod)

    with TestClient(main_mod.app) as test_client:
        yield test_client, main_mod, store_mod


def test_health(client):
    test_client, _, _ = client
    response = test_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_ready_checks_inference(client, monkeypatch):
    test_client, main_mod, _ = client
    monkeypatch.setattr(main_mod, "_check_inference", lambda: (True, "ok"))

    response = test_client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "inference": "ok"}


def test_health_ready_fails_when_inference_down(client, monkeypatch):
    test_client, main_mod, _ = client
    monkeypatch.setattr(
        main_mod, "_check_inference", lambda: (False, "connection refused")
    )

    response = test_client.get("/health/ready")
    assert response.status_code == 503


def test_ingest_raw_without_key_when_unconfigured(client, monkeypatch):
    test_client, _, _ = client
    monkeypatch.setattr(
        "app.inference.classify_and_sanitize",
        lambda body: {
            "category": "Billing",
            "urgency": "Medium",
            "sanitized_text": body,
            "summary": "test",
            "model": "mock",
        },
    )
    response = test_client.post(
        "/ingest/raw",
        json={
            "sender": "user@example.com",
            "subject": "Billing",
            "body": "Card 4111-1111-1111-1111 was charged twice.",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"].startswith("TICKET-")
    assert body["category"] in {"Billing", "General", "Tech Support", "Account Access"}


def test_ingest_raw_rejects_empty_body(client):
    test_client, _, _ = client
    response = test_client.post(
        "/ingest/raw",
        json={"sender": "a@b.com", "subject": "Test", "body": "   "},
    )
    assert response.status_code == 422


def test_ingest_raw_requires_key_when_configured(client, monkeypatch):
    test_client, main_mod, _ = client
    monkeypatch.setattr(main_mod, "INGEST_API_KEY", "secret-ingest")

    denied = test_client.post(
        "/ingest/raw",
        json={"sender": "a@b.com", "subject": "Test", "body": "Hello world"},
    )
    assert denied.status_code == 401

    allowed = test_client.post(
        "/ingest/raw",
        headers={"X-Ingest-Key": "secret-ingest"},
        json={"sender": "a@b.com", "subject": "Test", "body": "Hello world"},
    )
    assert allowed.status_code == 200


def test_ingest_upload_rejects_large_payload(client, monkeypatch):
    test_client, main_mod, _ = client
    monkeypatch.setattr(main_mod, "_MAX_UPLOAD_BYTES", 32)

    response = test_client.post(
        "/ingest",
        files={"file": ("big.eml", BytesIO(b"x" * 40), "message/rfc822")},
    )
    assert response.status_code == 413


def test_list_tickets_omits_vault(client):
    test_client, _, store_mod = client
    store_mod.create_ticket(
        sender="[EMAIL_1]",
        subject="Test",
        original_text="raw secret",
        sanitized_text="safe",
        category="General",
        urgency="Low",
        summary="",
        vault={"[EMAIL_1]": "a@b.com"},
        classification_ms=1.0,
        source="test",
        model="mock",
    )

    response = test_client.get("/tickets")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert "vault" not in payload[0]
    assert "original_text" not in payload[0]


def test_list_tickets_requires_key_when_configured(client, monkeypatch):
    test_client, main_mod, store_mod = client
    monkeypatch.setattr(main_mod, "INGEST_API_KEY", "secret-ingest")
    store_mod.create_ticket(
        sender="[EMAIL_1]",
        subject="Test",
        original_text="raw",
        sanitized_text="safe",
        category="General",
        urgency="Low",
        summary="",
        vault={},
        classification_ms=1.0,
        source="test",
        model="mock",
    )

    denied = test_client.get("/tickets")
    assert denied.status_code == 401

    allowed = test_client.get("/tickets", headers={"X-Ingest-Key": "secret-ingest"})
    assert allowed.status_code == 200
    assert len(allowed.json()) == 1


def test_list_tickets_pagination(client):
    test_client, _, store_mod = client
    for idx in range(3):
        store_mod.create_ticket(
            sender=f"user{idx}@example.com",
            subject=f"Ticket {idx}",
            original_text="raw",
            sanitized_text="safe",
            category="General",
            urgency="Low",
            summary="",
            vault={},
            classification_ms=1.0,
            source=f"test-{idx}",
            model="mock",
        )

    response = test_client.get("/tickets?limit=2&offset=1")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_vault_accepts_ingest_key(client, monkeypatch):
    test_client, main_mod, store_mod = client
    monkeypatch.setattr(main_mod, "VAULT_SECRET", "vault-secret")
    monkeypatch.setattr(main_mod, "INGEST_API_KEY", "ingest-secret")
    ticket = store_mod.create_ticket(
        sender="[EMAIL_1]",
        subject="Test",
        original_text="raw secret",
        sanitized_text="safe",
        category="General",
        urgency="Low",
        summary="",
        vault={"[EMAIL_1]": "a@b.com"},
        classification_ms=1.0,
        source="test",
        model="mock",
    )

    denied = test_client.get(f"/tickets/{ticket['id']}/vault")
    assert denied.status_code == 401

    allowed = test_client.get(
        f"/tickets/{ticket['id']}/vault",
        headers={"X-Ingest-Key": "ingest-secret"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["original_text"] == "raw secret"


def test_require_secrets_blocks_demo_defaults(client, monkeypatch):
    monkeypatch.setenv("REQUIRE_SECRETS", "1")
    monkeypatch.setenv("VAULT_SECRET", "helpdesk-demo-secret")

    import app.main as main_mod

    with pytest.raises(RuntimeError, match="VAULT_SECRET"):
        main_mod._validate_production_secrets()


def test_require_secrets_blocks_missing_ingest_key(client, monkeypatch):
    monkeypatch.setenv("REQUIRE_SECRETS", "1")
    monkeypatch.setenv("VAULT_SECRET", "production-secret")
    monkeypatch.delenv("INGEST_API_KEY", raising=False)

    import app.main as main_mod

    importlib.reload(main_mod)
    with pytest.raises(RuntimeError, match="INGEST_API_KEY"):
        main_mod._validate_production_secrets()


def test_lifespan_skips_smtp_when_require_secrets(client, monkeypatch):
    monkeypatch.setenv("REQUIRE_SECRETS", "1")
    monkeypatch.setenv("VAULT_SECRET", "production-secret")
    monkeypatch.setenv("INGEST_API_KEY", "ingest-secret")

    import app.main as main_mod

    importlib.reload(main_mod)
    controller = MagicMock()
    monkeypatch.setattr(main_mod, "Controller", controller)

    with TestClient(main_mod.app):
        pass

    controller.assert_not_called()
