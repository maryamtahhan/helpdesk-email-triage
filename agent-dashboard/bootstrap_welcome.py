#!/usr/bin/env python3
"""Write welcome page runtime config and nginx gateway proxy snippet."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/")
RUNTIME_DIR = os.environ.get("WELCOME_RUNTIME_DIR", "/tmp/helpdesk-runtime")
NGINX_SNIPPET = os.environ.get(
    "NGINX_GATEWAY_SNIPPET", "/tmp/helpdesk-runtime/nginx.gateway.conf"
)


def _probe_gateway() -> dict:
    try:
        with urllib.request.urlopen(f"{GATEWAY_URL}/health", timeout=4) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, OSError):
        return {}


def _inference_mode(classify_model: str) -> str:
    name = (classify_model or "").lower()
    if "mock" in name:
        return "mock"
    if name:
        return "rhaii"
    return "unknown"


def _upstream_host_port() -> tuple[str, int]:
    parsed = urllib.parse.urlparse(GATEWAY_URL)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port is not None:
        return host, parsed.port
    if parsed.scheme == "https":
        return host, 443
    return host, 80


def main() -> int:
    health = _probe_gateway()
    classify_model = str(health.get("classify_model", "") or "")
    mode = _inference_mode(classify_model)

    config = {
        "inference": mode,
        "classifyModel": classify_model,
        "gatewayProxyPrefix": "/api/gateway",
    }
    os.makedirs(RUNTIME_DIR, exist_ok=True)
    with open(os.path.join(RUNTIME_DIR, "welcome-config.json"), "w", encoding="utf-8") as fh:
        json.dump(config, fh)

    host, port = _upstream_host_port()
    snippet = f"""    location /api/gateway/ {{
        proxy_pass http://{host}:{port}/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
"""
    with open(NGINX_SNIPPET, "w", encoding="utf-8") as fh:
        fh.write(snippet)

    print(f"welcome-config: inference={mode} model={classify_model or '(unknown)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
