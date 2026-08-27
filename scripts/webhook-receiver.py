#!/usr/bin/env python3
"""Local webhook receiver for testing TICKET_SINK delivery.

Examples:
  # Listen until Ctrl-C
  ./scripts/webhook-receiver.py --port 9999 --secret demo-secret

  # Handle one POST then exit (used by test-webhook-sink.sh)
  ./scripts/webhook-receiver.py --once --port 9999 --secret demo-secret
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar


def verify_signature(body: bytes, secret: str, header: str) -> bool:
    if not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


class WebhookHandler(BaseHTTPRequestHandler):
    secret: ClassVar[str] = ""
    once: ClassVar[bool] = False
    deliveries: ClassVar[int] = 0
    server_ref: ClassVar[ThreadingHTTPServer | None] = None
    delivery_event: ClassVar[threading.Event | None] = None

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        sig = self.headers.get("X-Ticket-Signature", "")

        if self.secret:
            if not sig:
                self._respond(401, "Missing X-Ticket-Signature")
                return
            if not verify_signature(body, self.secret, sig):
                self._respond(401, "Invalid X-Ticket-Signature")
                return

        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            self._respond(400, "Invalid JSON body")
            return

        forbidden = {"vault", "original_text", "original_sender"} & payload.keys()
        if forbidden:
            self._respond(400, f"Unexpected fields in payload: {sorted(forbidden)}")
            return

        self.deliveries += 1
        ticket_id = payload.get("id", "?")
        print(f"[webhook] {self.path} ← {ticket_id}", flush=True)
        print(json.dumps(payload, indent=2, ensure_ascii=False), flush=True)

        self._respond(200, "ok")

        if self.once:
            if self.delivery_event is not None:
                self.delivery_event.set()
            if self.server_ref is not None:
                self.server_ref.shutdown()

    def _respond(self, code: int, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Receive TICKET_SINK webhook POSTs")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=9999, help="Listen port")
    parser.add_argument("--path", default="/hook", help="Expected URL path")
    parser.add_argument(
        "--secret",
        default="",
        help="Require and verify X-Ticket-Signature (HMAC-SHA256)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Exit after the first successful delivery",
    )
    args = parser.parse_args()

    WebhookHandler.secret = args.secret
    WebhookHandler.once = args.once
    delivery_event = threading.Event()
    WebhookHandler.delivery_event = delivery_event

    server = ThreadingHTTPServer((args.host, args.port), WebhookHandler)
    WebhookHandler.server_ref = server

    url = f"http://{args.host}:{args.port}{args.path}"
    print(f"Webhook receiver listening on {url}", flush=True)
    if args.secret:
        print("Signature verification: enabled", flush=True)
    if args.once:
        print("Mode: exit after first delivery", flush=True)
    print("Set TICKET_SINK=webhook:" + url, flush=True)
    print(flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)

    if args.once:
        delivery_event.wait(timeout=5.0)

    if args.once and not delivery_event.is_set():
        print("No webhook received.", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
