"""
command_guard.py — Hard denylist for shell commands, applied BEFORE the
user confirmation prompt.

This exists because any LLM (local open-source models especially — they are
more prone to garbled or overly-eager tool calls than a frontier hosted
model) can propose a destructive command. The confirmation prompt in
brain.py is the primary defense, but this module is a second, non-bypassable
layer: certain command patterns are refused outright and never even reach
the user for approval, because there's no legitimate reason a voice
assistant needs to run them.

This is deliberately conservative and will block some legitimate uses
(e.g. a real sysadmin task). Edit `_DENY_PATTERNS` if you understand the
risk and want to loosen it — but the default should stay strict, since the
entire point of a voice assistant is convenience, and convenience is
exactly what makes a moment of AI misjudgment costly.
"""

from __future__ import annotations

import re

_DENY_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("recursive force delete", re.compile(r"\brm\s+.*-[a-zA-Z]*r[a-zA-Z]*f|\brm\s+.*-[a-zA-Z]*f[a-zA-Z]*r", re.IGNORECASE)),
    ("filesystem wipe", re.compile(r"\bmkfs\b|\bdd\s+.*of=/dev/", re.IGNORECASE)),
    ("disk partitioning", re.compile(r"\bfdisk\b|\bparted\b", re.IGNORECASE)),
    ("privilege escalation", re.compile(r"\bsudo\b|\bsu\s+-|\brunas\b", re.IGNORECASE)),
    ("shutdown/reboot", re.compile(r"\bshutdown\b|\breboot\b|\bhalt\b|\binit\s+0\b", re.IGNORECASE)),
    ("fork bomb / infinite loop pattern", re.compile(r":\(\)\s*\{\s*:\|:&\s*\};|\bwhile\s*\(?true\)?\s*;?\s*do\b", re.IGNORECASE)),
    ("remote code execution pipe", re.compile(r"curl[^|]*\|\s*(sh|bash|zsh)\b|wget[^|]*\|\s*(sh|bash|zsh)\b", re.IGNORECASE)),
    ("credential/secret file access", re.compile(r"\.ssh/id_|\.aws/credentials|\.env\b|/etc/shadow|/etc/passwd", re.IGNORECASE)),
    ("permission wipe", re.compile(r"\bchmod\s+-R\s+777\b|\bchown\s+-R\b", re.IGNORECASE)),
    ("disk formatting", re.compile(r"\bformat\s+[a-zA-Z]:", re.IGNORECASE)),
    ("network exfil to raw IP with data flag", re.compile(r"\bnc\b.*-e\b|\bnetcat\b.*-e\b", re.IGNORECASE)),
]


def check(command: str) -> tuple[bool, str | None]:
    """Returns (is_blocked, reason). If is_blocked is True, the command
    must not be executed under any circumstances, regardless of user
    confirmation."""
    for label, pattern in _DENY_PATTERNS:
        if pattern.search(command):
            return True, label
    return False, None
