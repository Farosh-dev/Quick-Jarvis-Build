"""
logging_utils.py — Opt-in, always-redacted local logging.

Logging is OFF by default (JARVIS_ENABLE_LOGGING=false). When enabled, every
line is passed through pii_guard.redact_for_log() before being written, so
even if a user confirmed sending raw PII to Claude for that one turn, it
still never lands on disk in the clear.
"""

from __future__ import annotations

import datetime
import os
from pathlib import Path

from . import pii_guard

_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "conversation.log"


def log(role: str, text: str) -> None:
    if os.getenv("JARVIS_ENABLE_LOGGING", "false").lower() != "true":
        return
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    redacted = pii_guard.redact_for_log(text)
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {role}: {redacted}\n")
