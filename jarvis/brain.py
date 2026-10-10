"""
brain.py — The "reasoning core" using the Anthropic (Claude) API. Every tool
call Claude proposes is treated as a PROPOSAL only — it is checked against
the hard safety denylist and read back to the user for confirmation before
jarvis actually executes it (unless the tool is marked safe, e.g. read-only
actions like "get current time"). See jarvis/tools.py for the shared tool
definitions and execution/guardrail logic, and jarvis/brain_ollama.py for
the equivalent using a free, fully local open-source model instead.
"""

from __future__ import annotations

import os

from anthropic import Anthropic

from .tools import SAFE_TOOLS, TOOLS, execute_tool

SYSTEM_PROMPT = """You are JARVIS-lite, a helpful voice assistant running locally
on the user's machine. Be concise — your replies are spoken aloud, so avoid
long lists, code blocks, or markdown formatting. If the user asks you to do
something that requires a tool, propose the tool call; do not claim you did
something you didn't actually do. If a request is ambiguous or destructive,
ask a clarifying question instead of guessing."""


class Brain:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self._client = Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        self._model = model or os.getenv("JARVIS_MODEL", "claude-sonnet-4-5")
        self._history: list[dict] = []

    def reset(self) -> None:
        self._history = []

    def respond(self, user_text: str, ask_confirm) -> str:
        """Send `user_text` to Claude, resolving any tool calls (with
        guardrail checks + confirmation for non-safe tools) until we get a
        final text reply."""
        self._history.append({"role": "user", "content": user_text})

        while True:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=self._history,
            )

            self._history.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                text_blocks = [b.text for b in response.content if b.type == "text"]
                return " ".join(text_blocks).strip() or "(no response)"

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                confirm_fn = ask_confirm if block.name not in SAFE_TOOLS else (lambda _p: True)
                result_text = execute_tool(block.name, block.input, confirm_fn)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    }
                )

            self._history.append({"role": "user", "content": tool_results})
