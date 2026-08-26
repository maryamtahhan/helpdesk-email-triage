"""RFC-822 email parsing helpers."""

from __future__ import annotations

from email import policy
from email.message import EmailMessage
from email.parser import BytesParser


def parse_raw_email(raw_email_bytes: bytes) -> dict[str, str]:
    msg = BytesParser(policy=policy.default).parsebytes(raw_email_bytes)
    if not isinstance(msg, EmailMessage):
        msg = EmailMessage()
    body = ""
    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is not None:
        content = body_part.get_content()
        body = content if isinstance(content, str) else str(content)
    return {
        "sender": str(msg.get("From", "unknown")),
        "subject": str(msg.get("Subject", "(no subject)")),
        "body": body.strip(),
    }
