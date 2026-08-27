"""OpenAI-compatible mock used when Red Hat AI Inference is not available."""

from __future__ import annotations

import json
import re
import time

from fastapi import FastAPI
from pydantic import BaseModel, Field

# Simple name patterns — mirrors app/tokenizer.py regexes for demo parity
_NAME_INTRO = re.compile(
    r"\b(?:[Mm]y name is|[Ii](?: am|'m)|[Tt]his is)"
    r"\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"
)
_SIGNOFF = re.compile(
    r"(?:^|\n)\s*(?:[Tt]hanks|[Tt]hank you|[Rr]egards|[Bb]est|[Cc]heers)"
    r"[,]?\s*\n\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*$"
)

app = FastAPI(title="Helpdesk triage mock inference")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str = "mock-triage"
    messages: list[ChatMessage] = Field(default_factory=list)
    temperature: float = 0.0
    max_tokens: int = 256


class ResponsesRequest(BaseModel):
    model: str = "mock-triage"
    instructions: str | None = None
    input: str = ""
    temperature: float = 0.0


def _user_text(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""


def _redact_names(text: str) -> str:
    """Apply a residual name pass so the mock exercises the same contract as RHAII."""
    name_map: dict[str, str] = {}
    existing = re.findall(r"\[NAME_(\d+)\]", text)
    next_n = max((int(n) for n in existing), default=0) + 1

    def _sub(match: re.Match) -> str:
        nonlocal next_n
        full, name = match.group(0), match.group(1)
        if name not in name_map:
            name_map[name] = f"[NAME_{next_n}]"
            next_n += 1
        return full.replace(name, name_map[name])

    text = _NAME_INTRO.sub(_sub, text)
    text = _SIGNOFF.sub(_sub, text)
    return text


_SUMMARIES = {
    "Billing": "Billing issue reported; review account charges and respond.",
    "Account Access": "Account access blocked; restore credentials for customer.",
    "Tech Support": "Technical issue reported; investigate and provide resolution.",
    "General": "General inquiry received; no immediate action required.",
}


def _classify(text: str) -> dict[str, str]:
    lowered = text.lower()
    if "no action needed" in lowered or (
        "webinar" in lowered and "charge" not in lowered
    ):
        category = "General"
    elif any(
        word in lowered
        for word in (
            "charged", "invoice", "refund", "card was", "double charge",
            "payroll", "overtime", "insurer", "insurance", "emergency room",
        )
    ):
        category = "Billing"
    elif any(
        word in lowered for word in ("password", "lock", "mfa", "2fa", "reset")
    ):
        category = "Account Access"
    elif any(
        word in lowered
        for word in ("vpn", "crash", "error", "outage", "laptop", "wifi", "timeout")
    ):
        category = "Tech Support"
    elif "billing" in lowered:
        category = "Billing"
    else:
        category = "General"

    if "not urgent" in lowered:
        urgency = "Medium" if category != "General" else "Low"
    elif any(
        word in lowered
        for word in (
            "urgent", "asap", "immediately", "locked out", "charged twice",
            "missing overtime", "unexpected invoice",
        )
    ):
        urgency = "High"
    elif category == "General":
        urgency = "Low"
    else:
        urgency = "Medium"

    # Echo the body (structured PII already tokenized by the pipeline) and
    # apply a residual name pass so the mock exercises the same RHAII contract.
    marker = "Input Email:"
    body = text.split(marker, 1)[-1].strip() if marker in text else text
    sanitized = _redact_names(body)
    summary = _SUMMARIES.get(category, "Inquiry received.")
    return {
        "category": category,
        "urgency": urgency,
        "sanitized_text": sanitized,
        "redacted_text": sanitized,
        "summary": summary,
    }


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/models")
def models() -> dict:
    return {
        "object": "list",
        "data": [{"id": "mock-triage", "object": "model", "owned_by": "local-demo"}],
    }


@app.post("/v1/chat/completions")
def chat_completions(request: ChatRequest) -> dict:
    result = _classify(_user_text(request.messages))
    content = json.dumps(result)
    return {
        "id": "chatcmpl-mock-triage",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model or "mock-triage",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 1,
            "completion_tokens": 1,
            "total_tokens": 2,
        },
    }


@app.post("/v1/responses")
def responses(request: ResponsesRequest) -> dict:
    """Shape expected by the OpenAI Python SDK Responses API client."""
    result = _classify(request.input)
    content = json.dumps(result)
    return {
        "id": "resp-mock-triage",
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "model": request.model or "mock-triage",
        "output": [
            {
                "id": "msg-mock-triage",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": content}],
            }
        ],
    }
