"""FastAPI email gateway: REST tickets API, SMTP ingest, and .eml file watcher."""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from aiosmtpd.controller import Controller
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import store
from .pipeline import process_raw_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SMTP_PORT = int(os.environ.get("SMTP_PORT", "3025"))
INPUT_DIR = Path(os.environ.get("EMAIL_INPUT_DIR", "/app/input_emails"))
WATCH_INTERVAL = float(os.environ.get("WATCH_INTERVAL_SECONDS", "2"))


class _SmtpHandler:
    async def handle_DATA(self, server, session, envelope):  # noqa: N802
        process_raw_email(envelope.content, source="smtp")
        peer = getattr(session, "peer", "?")
        logger.info("Accepted SMTP message from %s", peer)
        return "250 Message accepted"


def _watch_loop() -> None:
    seen: set[str] = set()
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        for path in sorted(INPUT_DIR.glob("*.eml")):
            source = f"file:{path.name}"
            key = f"{path.name}:{path.stat().st_mtime_ns}"
            if key in seen or store.has_source(source):
                seen.add(key)
                continue
            try:
                process_raw_email(path.read_bytes(), source=source)
                seen.add(key)
                logger.info("Ingested %s", path.name)
            except Exception:
                logger.exception("Failed to ingest %s", path)
        time.sleep(WATCH_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.load()
    smtp = Controller(_SmtpHandler(), hostname="0.0.0.0", port=SMTP_PORT)
    smtp.start()
    logger.info("SMTP ingest listening on 0.0.0.0:%s", SMTP_PORT)
    watcher = None
    mode = os.environ.get("GATEWAY_MODE", "FILE_WATCHER").upper()
    if mode == "FILE_WATCHER":
        watcher = threading.Thread(target=_watch_loop, daemon=True, name="eml-watcher")
        watcher.start()
        logger.info("Watching %s for .eml files", INPUT_DIR)
    yield
    smtp.stop()


app = FastAPI(
    title="Helpdesk email gateway",
    description="Ingests support email, classifies it, and tokenizes PII.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/tickets")
def list_tickets() -> list[dict]:
    return store.list_public_tickets()


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str) -> dict:
    ticket = store.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.get("/tickets/{ticket_id}/vault")
def get_vault(ticket_id: str) -> dict:
    """Authorized rehydration: original body plus token map for this ticket."""
    ticket = store.get_ticket(ticket_id, include_vault=True)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {
        "id": ticket["id"],
        "original_text": ticket["original_text"],
        "vault": ticket["vault"],
        "sender": ticket["sender"],
    }


@app.post("/ingest")
async def ingest_upload(file: UploadFile = File(...)) -> dict:
    raw = await file.read()
    return process_raw_email(raw, source=f"upload:{file.filename or 'message.eml'}")


@app.post("/ingest/raw")
async def ingest_raw(payload: dict) -> dict:
    """JSON ingest for demos: {sender, subject, body}."""
    sender = str(payload.get("sender") or "demo@example.com")
    subject = str(payload.get("subject") or "(no subject)")
    body = str(payload.get("body") or "")
    if not body.strip():
        raise HTTPException(status_code=400, detail="body is required")
    from .pipeline import process_parsed_email

    return process_parsed_email(
        sender=sender,
        subject=subject,
        body=body,
        source="api",
    )
