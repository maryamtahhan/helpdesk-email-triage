"""FastAPI email gateway: REST tickets API, SMTP ingest, and .eml file watcher."""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from aiosmtpd.controller import Controller
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import store
from .pipeline import process_raw_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SMTP_PORT = int(os.environ.get("SMTP_PORT", "3025"))
SMTP_BIND = os.environ.get("SMTP_BIND", "127.0.0.1")
INPUT_DIR = Path(os.environ.get("EMAIL_INPUT_DIR", "/app/input_emails"))
WATCH_INTERVAL = float(os.environ.get("WATCH_INTERVAL_SECONDS", "2"))
# Set VAULT_SECRET in the environment to require an X-Vault-Secret header on
# vault requests. Leave unset for the demo path (a warning is logged on start).
VAULT_SECRET = os.environ.get("VAULT_SECRET", "")
# Streamlit UI origin; kept narrow so browsers can't make cross-origin vault requests.
_DASHBOARD_ORIGIN = os.environ.get("DASHBOARD_ORIGIN", "http://localhost:8501")


class _SmtpHandler:
    async def handle_DATA(self, server, session, envelope):  # noqa: N802
        import asyncio

        peer = getattr(session, "peer", "?")
        # Run classification in a thread so inference latency doesn't block
        # the aiosmtpd event loop and hold up subsequent SMTP connections.
        loop = asyncio.get_event_loop()
        fut = loop.run_in_executor(
            None, process_raw_email, envelope.content, "smtp"
        )

        def _log_exc(f: "asyncio.Future") -> None:
            exc = f.exception()
            if exc:
                logger.error(
                    "SMTP ingest failed for message from %s: %s", peer, exc
                )

        fut.add_done_callback(_log_exc)
        logger.info("Accepted SMTP from %s (processing in background)", peer)
        return "250 Message accepted"


def _watch_loop() -> None:
    seen: set[str] = set()
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        for path in sorted(INPUT_DIR.glob("*.eml")):
            mtime = path.stat().st_mtime_ns
            # Include mtime in both key and source so a modified file gets a
            # fresh source ID and is re-ingested rather than silently skipped.
            source = f"file:{path.name}:{mtime}"
            if source in seen or store.has_source(source):
                seen.add(source)
                continue
            try:
                process_raw_email(path.read_bytes(), source=source)
                seen.add(source)
                logger.info("Ingested %s", path.name)
            except Exception:
                logger.exception("Failed to ingest %s", path)
        time.sleep(WATCH_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.load()
    if SMTP_BIND == "0.0.0.0":
        logger.warning(
            "SMTP listener bound to all interfaces (0.0.0.0:%s) with no auth. "
            "Set SMTP_BIND=127.0.0.1 or place behind a firewall for any real deployment.",
            SMTP_PORT,
        )
    if not VAULT_SECRET:
        logger.warning(
            "VAULT_SECRET is not set — vault endpoint is unauthenticated. "
            "Set VAULT_SECRET in the environment before any real deployment."
        )
    smtp = Controller(_SmtpHandler(), hostname=SMTP_BIND, port=SMTP_PORT)
    smtp.start()
    logger.info("SMTP ingest listening on %s:%s", SMTP_BIND, SMTP_PORT)
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
    allow_origins=[_DASHBOARD_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["X-Vault-Secret"],
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
def get_vault(
    ticket_id: str,
    x_vault_secret: str = Header(default=""),
) -> dict:
    """Authorized rehydration: original body plus token map for this ticket."""
    if VAULT_SECRET and x_vault_secret != VAULT_SECRET:
        raise HTTPException(status_code=401, detail="Invalid vault secret")
    ticket = store.get_ticket(ticket_id, include_vault=True)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return {
        "id": ticket["id"],
        "original_text": ticket["original_text"],
        "vault": ticket["vault"],
        "sender": ticket["sender"],
        "original_sender": ticket.get("original_sender", ticket["sender"]),
    }


_MAX_UPLOAD_BYTES = 1024 * 1024  # 1 MiB


@app.post("/ingest")
async def ingest_upload(file: UploadFile = File(...)) -> dict:
    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Email too large (max 1 MiB)")
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
