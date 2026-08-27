"""OpenAI-compatible mock used when Red Hat AI Inference is not available."""

from __future__ import annotations

import json
import time

from fastapi import FastAPI
from pydantic import BaseModel, Field

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
    elif any(word in lowered for word in ("password", "lock", "mfa", "2fa", "reset")):
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

    # The gateway already regex-tokenizes structured PII. Echo the input email
    # section so the UI still shows tokens the regex layer produced.
    marker = "Input Email:"
    sanitized = text.split(marker, 1)[-1].strip() if marker in text else text
    return {
        "category": category,
        "urgency": urgency,
        "sanitized_text": sanitized,
        "redacted_text": sanitized,
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
