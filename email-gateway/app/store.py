"""In-memory ticket store with JSON persistence and a PII vault."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_tickets: list[dict[str, Any]] = []
_next_id = 8921


def _data_dir() -> Path:
    path = Path(os.environ.get("TICKET_DATA_DIR", "/app/data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _tickets_path() -> Path:
    return _data_dir() / "tickets.json"


def load() -> None:
    global _tickets, _next_id
    path = _tickets_path()
    if not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    _tickets = payload.get("tickets", [])
    _next_id = int(payload.get("next_id", 8921))


def _persist() -> None:
    payload = {"next_id": _next_id, "tickets": _tickets}
    _tickets_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def create_ticket(
    *,
    sender: str,
    subject: str,
    original_text: str,
    sanitized_text: str,
    category: str,
    urgency: str,
    vault: dict[str, str],
    classification_ms: float,
    source: str,
    model: str,
) -> dict[str, Any]:
    global _next_id
    with _lock:
        ticket_id = f"TICKET-{_next_id}"
        _next_id += 1
        ticket = {
            "id": ticket_id,
            "sender": sender,
            "subject": subject,
            "original_text": original_text,
            "sanitized_text": sanitized_text,
            "category": category,
            "urgency": urgency,
            "vault": vault,
            "classification_ms": round(classification_ms, 1),
            "source": source,
            "model": model,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _tickets.insert(0, ticket)
        _persist()
        return ticket


def has_source(source: str) -> bool:
    with _lock:
        return any(ticket.get("source") == source for ticket in _tickets)


def list_public_tickets() -> list[dict[str, Any]]:
    with _lock:
        return [_public(ticket) for ticket in _tickets]


def get_ticket(ticket_id: str, include_vault: bool = False) -> dict[str, Any] | None:
    with _lock:
        for ticket in _tickets:
            if ticket["id"] == ticket_id:
                return ticket if include_vault else _public(ticket)
    return None


def _public(ticket: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ticket["id"],
        "sender": ticket["sender"],
        "subject": ticket["subject"],
        "sanitized_text": ticket["sanitized_text"],
        "category": ticket["category"],
        "urgency": ticket["urgency"],
        "classification_ms": ticket["classification_ms"],
        "source": ticket["source"],
        "model": ticket["model"],
        "created_at": ticket["created_at"],
        "token_count": len(ticket.get("vault") or {}),
    }
