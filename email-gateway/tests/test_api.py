import importlib
from io import BytesIO

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


def test_ingest_raw_without_key_when_unconfigured(client):
    test_client, _, _ = client
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


def test_require_secrets_blocks_demo_defaults(client, monkeypatch):
    monkeypatch.setenv("REQUIRE_SECRETS", "1")
    monkeypatch.setenv("VAULT_SECRET", "helpdesk-demo-secret")

    import app.main as main_mod

    with pytest.raises(RuntimeError, match="VAULT_SECRET"):
        main_mod._validate_production_secrets()
