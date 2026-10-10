"""
pii_guard.py — Guardrail that stops personally-identifiable information (PII)
from silently leaving this machine.

Design goals:
  1. Detect likely PII in a transcript using cheap, local regex heuristics
     (no data leaves the machine to do this check).
  2. If PII is found, mask it and show the user exactly what was detected.
  3. Refuse to forward the ORIGINAL (unmasked) text to Claude, a log file,
     or any other sink until the user explicitly confirms.
  4. Default to the safe choice: if the user doesn't answer clearly, treat
     it as "no".

This is a heuristic layer, not a certified PII-detection engine. It is
intentionally conservative (prefers false positives over false negatives)
because the cost of over-asking is a confirmation prompt, while the cost of
under-asking is a real data leak.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class PIIType(str, Enum):
    EMAIL = "email address"
    PHONE = "phone number"
    CREDIT_CARD = "card number"
    SSN_US = "US Social Security Number"
    AADHAAR = "Aadhaar-like ID number"
    IP_ADDRESS = "IP address"
    PHYSICAL_ADDRESS = "street address"
    DOB = "date of birth"
    BANK_ACCOUNT = "bank account / IBAN number"


@dataclass
class PIIMatch:
    kind: PIIType
    original: str
    start: int
    end: int


@dataclass
class PIIScanResult:
    has_pii: bool
    masked_text: str
    matches: list[PIIMatch] = field(default_factory=list)

    def summary(self) -> str:
        if not self.has_pii:
            return "No PII detected."
        kinds = sorted({m.kind.value for m in self.matches})
        return "Detected possible: " + ", ".join(kinds)


# Order matters a little (more specific patterns first) but each pattern is
# checked independently against the whole string.
_PATTERNS: list[tuple[PIIType, re.Pattern]] = [
    (PIIType.EMAIL, re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")),
    # Credit / debit card: 13-19 digits, optionally grouped in 4s with spaces/dashes
    (PIIType.CREDIT_CARD, re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    # US SSN: 123-45-6789
    (PIIType.SSN_US, re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # Aadhaar (India): 12 digits, often grouped as 4-4-4
    (PIIType.AADHAAR, re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")),
    # IBAN-ish / long bank account numbers
    (PIIType.BANK_ACCOUNT, re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
    # Phone numbers: loose international/local pattern, 7-15 digits with
    # optional +, spaces, dashes, parens
    (
        PIIType.PHONE,
        re.compile(r"(?<!\d)(?:\+?\d{1,3}[ -]?)?(?:\(?\d{2,4}\)?[ -]?)?\d{3,4}[ -]?\d{3,4}(?!\d)"),
    ),
    (PIIType.IP_ADDRESS, re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    # Date of birth style phrases (very rough — flags "DOB", "born on", etc. near a date)
    (
        PIIType.DOB,
        re.compile(
            r"\b(?:dob|date of birth|born on)\b[^.\n]{0,20}\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
            re.IGNORECASE,
        ),
    ),
    # Street address: number + word(s) + common street suffix
    (
        PIIType.PHYSICAL_ADDRESS,
        re.compile(
            r"\b\d{1,5}\s+[A-Za-z0-9.\s]{2,40}\b(street|st|road|rd|avenue|ave|lane|ln|"
            r"drive|dr|nagar|colony|apartment|apt|block)\b",
            re.IGNORECASE,
        ),
    ),
]


def _mask(value: str) -> str:
    """Mask a matched PII string, keeping a small hint of its shape."""
    stripped = re.sub(r"\s", "", value)
    if len(stripped) <= 4:
        return "*" * len(value)
    visible = 2
    return value[:visible] + "*" * max(3, len(value) - visible * 2) + value[-visible:]


def scan(text: str) -> PIIScanResult:
    """Scan `text` for likely PII. Never sends `text` anywhere — pure local regex."""
    matches: list[PIIMatch] = []
    seen_spans: set[tuple[int, int]] = set()

    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            # Skip near-duplicate overlapping matches (e.g. phone vs aadhaar
            # both matching the same digit run) to avoid double-masking.
            if any(not (span[1] <= s[0] or span[0] >= s[1]) for s in seen_spans):
                continue
            seen_spans.add(span)
            matches.append(PIIMatch(kind=kind, original=m.group(0), start=span[0], end=span[1]))

    if not matches:
        return PIIScanResult(has_pii=False, masked_text=text, matches=[])

    matches.sort(key=lambda m: m.start)
    masked_parts = []
    cursor = 0
    for m in matches:
        masked_parts.append(text[cursor:m.start])
        masked_parts.append(_mask(m.original))
        cursor = m.end
    masked_parts.append(text[cursor:])
    masked_text = "".join(masked_parts)

    return PIIScanResult(has_pii=True, masked_text=masked_text, matches=matches)


def guard_text(
    text: str,
    ask_confirm,
    *,
    context: str = "send this to Claude",
) -> tuple[bool, str]:
    """
    Run the PII guard over `text`.

    `ask_confirm` is a callable: (prompt: str) -> bool, supplied by the
    caller (assistant.py) so this module stays free of any I/O assumptions
    (works the same whether input comes from voice or keyboard).

    Returns (allowed, text_to_use):
      - If no PII found: (True, original text) — nothing to confirm.
      - If PII found and user confirms: (True, original text).
      - If PII found and user declines (or gives no clear answer): (False, masked_text)
        — caller should NOT send the original text anywhere; it may still
        act on the masked version or ask the user to rephrase.
    """
    result = scan(text)
    if not result.has_pii:
        return True, text

    prompt = (
        f"⚠️  {result.summary()}\n"
        f"Masked preview: \"{result.masked_text}\"\n"
        f"Do you want to {context} WITH the unmasked details? (yes/no): "
    )
    confirmed = bool(ask_confirm(prompt))
    if confirmed:
        return True, text
    return False, result.masked_text


def redact_for_log(text: str) -> str:
    """Always-on redaction for anything written to disk, regardless of the
    user's confirmation above — logs should never contain raw PII."""
    return scan(text).masked_text
