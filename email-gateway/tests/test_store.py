import importlib
import json


def test_load_rebuilds_indexes(tmp_path, monkeypatch):
    monkeypatch.setenv("TICKET_DATA_DIR", str(tmp_path))
    data = {
        "next_id": 9002,
        "tickets": [
            {
                "id": "TICKET-9001",
                "sender": "[EMAIL_1]",
                "subject": "Hi",
                "original_text": "x",
                "original_sender": "a@b.com",
                "sanitized_text": "x",
                "summary": "",
                "category": "General",
                "urgency": "Low",
                "vault": {},
                "classification_ms": 1.0,
                "source": "file-watcher:sample.eml",
                "model": "mock-triage",
                "created_at": "2026-08-27T18:00:00+00:00",
            }
        ],
    }
    (tmp_path / "tickets.json").write_text(json.dumps(data), encoding="utf-8")

    import app.store as store_mod

    importlib.reload(store_mod)
    store_mod.load()

    assert store_mod.get_ticket("TICKET-9001") is not None
    assert store_mod.has_source("file-watcher:sample.eml")
    assert store_mod.get_ticket("TICKET-missing") is None
