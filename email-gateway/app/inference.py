"""Adapter around the reused vLLM email classification gateway."""

from __future__ import annotations

import json
import os
import re
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any

_GATEWAY_ROOT = Path(__file__).resolve().parents[1]
if str(_GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(_GATEWAY_ROOT))

from gateways.email_classification_gateway import VLLMEmailGateway  # noqa: E402

CATEGORIES = {"Billing", "Tech Support", "Account Access", "General"}
URGENCIES = {"Low", "Medium", "High"}


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.sub(r"^```(?:json)?\s*", "", stripped)
    fenced = re.sub(r"\s*```$", "", fenced)
    start = fenced.find("{")
    end = fenced.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Model response did not contain a JSON object")
    return json.loads(fenced[start : end + 1])


def env_config() -> dict[str, Any]:
    config_path = os.environ.get("VLLM_GW_CONFIG")
    if config_path:
        with open(config_path, encoding="ascii") as handle:
            return json.load(handle)
    endpoint = os.environ.get("VLLM_BASE_URL")
    if not endpoint:
        raw = os.environ.get(
            "VLLM_ENDPOINT", "http://rhaii-cpu-engine:8000/v1/chat/completions"
        )
        endpoint = raw.replace("/chat/completions", "")
    return {
        "verbose": 0,
        "base_url": endpoint.rstrip("/"),
        "classify_model": os.environ.get(
            "MODEL_NAME", "Qwen/Qwen2.5-1.5B-Instruct"
        ),
    }


def _normalize(parsed: dict[str, Any], fallback_text: str, model: str) -> dict[str, Any]:
    category = str(parsed.get("category", "General")).strip()
    urgency = str(parsed.get("urgency", "Medium")).strip()
    sanitized = str(
        parsed.get("sanitized_text") or parsed.get("redacted_text") or fallback_text
    ).strip()
    if category not in CATEGORIES:
        category = "General"
    if urgency not in URGENCIES:
        urgency = "Medium"
    return {
        "category": category,
        "urgency": urgency,
        "sanitized_text": sanitized,
        "model": model,
    }


def classify_raw_email(raw_email_bytes: bytes) -> dict[str, Any]:
    """Run the original MIME-to-vLLM gateway against an RFC-822 payload."""
    config = env_config()
    gateway = VLLMEmailGateway(config)
    gateway.parse_bytes(raw_email_bytes)
    gateway.execute()
    if gateway.response is None:
        raise RuntimeError("No text/plain part found in message")
    parsed = extract_json_object(gateway.response.output_text)
    return _normalize(parsed, "", config["classify_model"])


def classify_and_sanitize(body: str) -> dict[str, Any]:
    """Wrap a plain body in MIME so the same gateway can classify API ingest."""
    message = EmailMessage()
    message["From"] = "ingest@local"
    message["Subject"] = "Support message"
    message.set_content(body)
    return classify_raw_email(bytes(message))
