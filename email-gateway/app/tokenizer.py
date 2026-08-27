"""Regex-based structured PII detection and reversible tokenization."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TOKEN_TYPES = ("CARD_LAST4", "PHONE", "EMAIL", "ACCOUNT_ID", "SSN", "NAME")

_CARD_RE = re.compile(r"\b(?:\d[ \-]?){13,19}\b")
_PHONE_RE = re.compile(
    r"(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b"
)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_ACCOUNT_RE = re.compile(r"\bACC-\d{3,}\b", re.IGNORECASE)
_NAME_INTRO_RE = re.compile(
    r"\b(?:[Mm]y name is|[Ii](?: am|'m)|[Tt]his is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)"
)
_SIGNOFF_RE = re.compile(
    r"(?:^|\n)\s*(?:[Tt]hanks|[Tt]hank you|[Rr]egards|[Bb]est|[Cc]heers)[,]?\s*\n\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*$"
)


@dataclass
class TokenVault:
    """Maps opaque tokens such as [PHONE_1] back to the original values."""

    mapping: dict[str, str] = field(default_factory=dict)
    _counts: dict[str, int] = field(default_factory=dict)

    def add(self, token_type: str, value: str) -> str:
        for existing_token, existing_value in self.mapping.items():
            if existing_value == value and existing_token.startswith(f"[{token_type}_"):
                return existing_token
        self._counts[token_type] = self._counts.get(token_type, 0) + 1
        token = f"[{token_type}_{self._counts[token_type]}]"
        self.mapping[token] = value
        return token


def _luhn_ok(digits: str) -> bool:
    total = 0
    reverse = digits[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def tokenize_structured_pii(
    text: str, vault: TokenVault | None = None
) -> tuple[str, TokenVault]:
    """Replace high-confidence PII with reversible tokens.

    Cards, phones, emails, SSNs, account IDs, and obvious name phrases are
    swapped before the model sees the payload. The original values stay in
    the returned vault so an authorized agent can rehydrate a ticket.

    Pass an existing vault to extend the same token namespace across multiple
    fields (e.g. subject and sender share tokens with the body).
    """
    if vault is None:
        vault = TokenVault()
    sanitized = text

    def _sub_card(match: re.Match[str]) -> str:
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 13 or len(digits) > 19:
            return raw
        if not _luhn_ok(digits):
            return raw
        # Store only the last 4 digits — never the full PAN.
        return vault.add("CARD_LAST4", f"****-{digits[-4:]}")

    sanitized = _CARD_RE.sub(_sub_card, sanitized)

    def _sub_generic(token_type: str):
        def _replace(match: re.Match[str]) -> str:
            return vault.add(token_type, match.group(0))

        return _replace

    sanitized = _SSN_RE.sub(_sub_generic("SSN"), sanitized)
    sanitized = _PHONE_RE.sub(_sub_generic("PHONE"), sanitized)
    sanitized = _EMAIL_RE.sub(_sub_generic("EMAIL"), sanitized)

    def _sub_account(match: re.Match[str]) -> str:
        return vault.add("ACCOUNT_ID", match.group(0))

    sanitized = _ACCOUNT_RE.sub(_sub_account, sanitized)

    def _sub_name(match: re.Match[str]) -> str:
        full = match.group(0)
        name = match.group(1)
        token = vault.add("NAME", name)
        return full.replace(name, token)

    sanitized = _NAME_INTRO_RE.sub(_sub_name, sanitized)
    sanitized = _SIGNOFF_RE.sub(_sub_name, sanitized)
    return sanitized, vault


CATEGORIES = ("Billing", "Tech Support", "Account Access", "General")
URGENCIES = ("Low", "Medium", "High")

_BILLING_HINTS = (
    "invoice",
    "charged",
    "charge",
    "refund",
    "payment",
    "billing",
    "card",
    "double",
)
_TECH_HINTS = (
    "vpn",
    "outage",
    "crash",
    "error",
    "timeout",
    "wifi",
    "laptop",
    "software",
    "bug",
)
_ACCESS_HINTS = (
    "password",
    "lockout",
    "locked",
    "mfa",
    "2fa",
    "reset",
    "cannot log",
    "can't log",
    "unlock",
)
_HIGH_HINTS = (
    "urgent",
    "immediately",
    "asap",
    "locked out",
    "cannot access",
    "can't access",
    "charged twice",
    "fraud",
    "down",
)


def heuristic_triage(text: str) -> tuple[str, str]:
    """Keyword fallback when the model is unreachable or returns invalid JSON."""
    lowered = text.lower()
    if "no action needed" in lowered:
        return "General", "Low"
    category = "General"
    scores = {
        "Billing": sum(1 for h in _BILLING_HINTS if h in lowered),
        "Tech Support": sum(1 for h in _TECH_HINTS if h in lowered),
        "Account Access": sum(1 for h in _ACCESS_HINTS if h in lowered),
    }
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        category = best
    urgency = "High" if any(h in lowered for h in _HIGH_HINTS) else "Medium"
    if category == "General" and urgency != "High":
        urgency = "Low"
    return category, urgency
