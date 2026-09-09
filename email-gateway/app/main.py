"""FastAPI email gateway: REST tickets API, SMTP ingest, and .eml file watcher."""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from aiosmtpd.controller import Controller
from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

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
INGEST_API_KEY = os.environ.get("INGEST_API_KEY", "")
_DEMO_VAULT_SECRET = "helpdesk-demo-secret"
# Streamlit UI origin; kept narrow so browsers can't make cross-origin vault requests.
_DASHBOARD_ORIGIN = os.environ.get("DASHBOARD_ORIGIN", "http://localhost:8501")
_DEFAULT_LIST_LIMIT = 100
_MAX_LIST_LIMIT = 500


class IngestRawRequest(BaseModel):
    sender: str = "demo@example.com"
    subject: str = "(no subject)"
    body: str

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body is required")
        return value


def _secrets_enabled() -> bool:
    return os.environ.get("REQUIRE_SECRETS", "").lower() in {"1", "true", "yes"}


def _secret_matches(provided: str, expected: str) -> bool:
    if not expected:
        return True
    if not provided or len(provided) != len(expected):
        return False
    return secrets.compare_digest(provided, expected)


def _require_ingest_key(x_ingest_key: str) -> None:
    if INGEST_API_KEY and not _secret_matches(x_ingest_key, INGEST_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid ingest API key")


def _require_vault_access(x_vault_secret: str, x_ingest_key: str) -> None:
    if not VAULT_SECRET:
        return
    if _secret_matches(x_vault_secret, VAULT_SECRET):
        return
    if INGEST_API_KEY and _secret_matches(x_ingest_key, INGEST_API_KEY):
        return
    raise HTTPException(status_code=401, detail="Invalid vault secret")


def _check_inference() -> tuple[bool, str]:
    base = os.environ.get(
        "VLLM_BASE_URL",
        os.environ.get(
            "VLLM_ENDPOINT", "http://inference-mock:8000/v1/chat/completions"
        ),
    )
    if "/chat/completions" in base:
        base = base.replace("/chat/completions", "")
    url = f"{base.rstrip('/')}/models"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status != 200:
                return False, f"HTTP {response.status}"
    except urllib.error.URLError as exc:
        return False, str(exc.reason)
    except Exception as exc:
        return False, str(exc)
    return True, "ok"


def _validate_production_secrets() -> None:
    if os.environ.get("REQUIRE_SECRETS", "").lower() not in {"1", "true", "yes"}:
        return
    if not VAULT_SECRET or VAULT_SECRET == _DEMO_VAULT_SECRET:
        raise RuntimeError(
            "REQUIRE_SECRETS is set but VAULT_SECRET is missing or still the demo value"
        )
    if not INGEST_API_KEY:
        raise RuntimeError(
            "REQUIRE_SECRETS is set but INGEST_API_KEY is not configured"
        )


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

        def _log_exc(f: asyncio.Future) -> None:
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
    _validate_production_secrets()
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
    elif VAULT_SECRET == _DEMO_VAULT_SECRET:
        logger.warning(
            "VAULT_SECRET is still the demo default — replace before any real deployment."
        )
    if INGEST_API_KEY:
        logger.info(
            "HTTP ingest and ticket list endpoints require X-Ingest-Key header"
        )
    elif not _secrets_enabled():
        logger.warning(
            "INGEST_API_KEY is not set — POST /ingest, /ingest/raw, and GET /tickets "
            "are unauthenticated."
        )
    smtp = None
    if _secrets_enabled():
        logger.info("SMTP ingest disabled (REQUIRE_SECRETS is set)")
    else:
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
    if smtp is not None:
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
    allow_headers=["X-Vault-Secret", "X-Ingest-Key"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready() -> dict[str, str]:
    inference_ok, inference_detail = _check_inference()
    if not inference_ok:
        raise HTTPException(
            status_code=503,
            detail={"status": "not ready", "inference": inference_detail},
        )
    return {"status": "ready", "inference": "ok"}


@app.get("/tickets")
def list_tickets(
    x_ingest_key: Annotated[str, Header()] = "",
    limit: int = Query(default=_DEFAULT_LIST_LIMIT, ge=1, le=_MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    _require_ingest_key(x_ingest_key)
    return store.list_public_tickets(limit=limit, offset=offset)


@app.get("/tickets/{ticket_id}")
def get_ticket(
    ticket_id: str, x_ingest_key: Annotated[str, Header()] = ""
) -> dict:
    _require_ingest_key(x_ingest_key)
    ticket = store.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


@app.get("/tickets/{ticket_id}/vault")
def get_vault(
    ticket_id: str,
    x_vault_secret: Annotated[str, Header()] = "",
    x_ingest_key: Annotated[str, Header()] = "",
) -> dict:
    """Authorized rehydration: original body plus token map for this ticket."""
    _require_vault_access(x_vault_secret, x_ingest_key)
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
async def ingest_upload(
    file: UploadFile = File(...),
    x_ingest_key: Annotated[str, Header()] = "",
) -> dict:
    _require_ingest_key(x_ingest_key)
    import asyncio

    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Email too large (max 1 MiB)")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        process_raw_email,
        raw,
        f"upload:{file.filename or 'message.eml'}",
    )


@app.post("/ingest/raw")
async def ingest_raw(
    payload: IngestRawRequest,
    x_ingest_key: Annotated[str, Header()] = "",
) -> dict:
    """JSON ingest for demos: {sender, subject, body}."""
    _require_ingest_key(x_ingest_key)
    from .pipeline import process_parsed_email

    return process_parsed_email(
        sender=payload.sender,
        subject=payload.subject,
        body=payload.body,
        source="api",
    )
