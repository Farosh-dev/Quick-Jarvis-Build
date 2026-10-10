"""
tools.py — Shared tool definitions and execution, used by BOTH the Claude
backend (brain.py) and the local Ollama backend (brain_ollama.py), so the
guardrails are identical no matter which "brain" you choose.

Execution order for any tool with side effects:
  1. command_guard hard denylist  -> if blocked, refuse outright, no prompt.
  2. user confirmation prompt      -> if declined, don't run it.
  3. only then does it execute.
"""

from __future__ import annotations

import datetime
import subprocess

from . import command_guard

TOOLS = [
    {
        "name": "get_current_time",
        "description": "Get the current local date and time.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "run_shell_command",
        "description": (
            "Run a shell command on the user's machine and return its output. "
            "Use this only when the user clearly asked you to perform a system "
            "action (e.g. 'open my downloads folder', 'check disk space'). "
            "This is a powerful, potentially destructive tool — it will always "
            "be checked against a safety denylist and confirmed with the user "
            "before running."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run."},
                "reason": {
                    "type": "string",
                    "description": "One short sentence explaining why this command is needed.",
                },
            },
            "required": ["command", "reason"],
        },
    },
]

# Tools that never touch the filesystem/network/OS state and therefore don't
# need a confirmation prompt each time.
SAFE_TOOLS = {"get_current_time"}


def execute_tool(name: str, tool_input: dict, ask_confirm) -> str:
    if name == "get_current_time":
        return datetime.datetime.now().strftime("%A, %d %B %Y, %I:%M %p")

    if name == "run_shell_command":
        command = tool_input.get("command", "")
        reason = tool_input.get("reason", "(no reason given)")

        blocked, why = command_guard.check(command)
        if blocked:
            return (
                f"BLOCKED: this command was refused automatically (matched the "
                f"'{why}' safety rule) and was never shown to the user for "
                f"approval. Do not attempt an equivalent workaround."
            )

        prompt = (
            f"JARVIS wants to run this shell command:\n"
            f"    {command}\n"
            f"Reason: {reason}\n"
            f"Allow it? (yes/no): "
        )
        if not ask_confirm(prompt):
            return "User declined to run this command. Do not attempt it again this turn."
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            output = (result.stdout or "") + (result.stderr or "")
            return output.strip()[:4000] or "(command produced no output)"
        except Exception as exc:  # noqa: BLE001
            return f"Command failed: {exc}"

    return f"Unknown tool: {name}"
