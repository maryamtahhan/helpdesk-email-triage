"""Public triage output contract for HTTP consumers and webhook sinks."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TriageResult(BaseModel):
    """Sanitized ticket payload safe for downstream queues and webhooks.

    Never includes original_text, original_sender, or the vault map.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    sender: str
    subject: str
    sanitized_text: str
    summary: str = ""
    category: str
    urgency: str
    classification_ms: float
    source: str
    model: str
    created_at: str
    token_count: int = Field(ge=0)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_ticket(cls, ticket: dict[str, Any]) -> TriageResult:
        """Build from a full stored ticket (vault fields are ignored)."""
        return cls(
            id=ticket["id"],
            sender=ticket["sender"],
            subject=ticket["subject"],
            sanitized_text=ticket["sanitized_text"],
            summary=ticket.get("summary", ""),
            category=ticket["category"],
            urgency=ticket["urgency"],
            classification_ms=float(ticket["classification_ms"]),
            source=ticket["source"],
            model=ticket["model"],
            created_at=ticket["created_at"],
            token_count=len(ticket.get("vault") or {}),
        )

    @classmethod
    def from_public_dict(cls, data: dict[str, Any]) -> TriageResult:
        """Build from a public ticket dict (GET /tickets response shape)."""
        return cls.model_validate(data)
