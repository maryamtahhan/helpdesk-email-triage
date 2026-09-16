"""RFC-822 email parsing helpers."""

from __future__ import annotations

import html
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from html.parser import HTMLParser

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_WS_RE = re.compile(r"[ \t\f\r]+\n?\s*|\n{3,}")


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join(self._parts)


def _html_to_text(content: str) -> str:
    """Strip HTML so markup and script bodies do not reach the classifier."""
    without_blocks = _SCRIPT_STYLE_RE.sub(" ", content)
    parser = _HTMLTextExtractor()
    parser.feed(without_blocks)
    parser.close()
    text = html.unescape(parser.text())
    return _WS_RE.sub(" ", text).strip()


def parse_raw_email(raw_email_bytes: bytes) -> dict[str, str]:
    msg = BytesParser(policy=policy.default).parsebytes(raw_email_bytes)
    if not isinstance(msg, EmailMessage):
        msg = EmailMessage()
    body = ""
    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is not None:
        content = body_part.get_content()
        if isinstance(content, bytes):
            content = content.decode("utf-8", "replace")
        if body_part.get_content_subtype() == "html":
            body = _html_to_text(str(content))
        else:
            body = content if isinstance(content, str) else str(content)
    return {
        "sender": str(msg.get("From", "unknown")),
        "subject": str(msg.get("Subject", "(no subject)")),
        "body": body.strip(),
    }
