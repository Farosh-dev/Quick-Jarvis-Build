"""
brain_ollama.py — Alternative "reasoning core" using a fully local,
open-source model served by Ollama (https://ollama.com), instead of the
paid Claude API.

Why this exists: it costs nothing per request (no API billing at all) and,
combined with the local STT/TTS already in this project, means NOTHING
about your conversation ever leaves your machine — the strongest possible
privacy posture, at the cost of noticeably weaker reasoning and tool-use
reliability compared to Claude.

Because local models are more prone to malformed or overly-eager tool
calls, this backend uses the exact same shared guardrails as brain.py
(jarvis/tools.py: hard denylist + confirmation), so switching backends
never weakens the safety model — only the answer quality.

Setup:
    1. Install Ollama: https://ollama.com/download
    2. Pull a tool-calling-capable model, e.g.:
         ollama pull llama3.1:8b
       (qwen2.5:7b and mistral-nemo also support tool calling well)
    3. In .env: JARVIS_BACKEND=ollama, OLLAMA_MODEL=llama3.1:8b
"""

from __future__ import annotations

import json
import os

import requests

from .tools import SAFE_TOOLS, TOOLS, execute_tool

SYSTEM_PROMPT = """You are JARVIS-lite, a helpful voice assistant running locally
on the user's machine. Be concise — your replies are spoken aloud, so avoid
long lists, code blocks, or markdown formatting. If the user asks you to do
something that requires a tool, call the tool; do not claim you did
something you didn't actually do. If a request is ambiguous or destructive,
ask a clarifying question instead of guessing."""


def _to_openai_tool_schema(tools: list[dict]) -> list[dict]:
    """Ollama's /api/chat tool-calling format mirrors OpenAI's function
    schema, which differs slightly from Anthropic's (parameters vs
    input_schema)."""
    converted = []
    for t in tools:
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
        )
    return converted


class OllamaBrain:
    def __init__(self, model: str | None = None, host: str | None = None):
        self._model = model or os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        self._host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self._history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self._tools = _to_openai_tool_schema(TOOLS)

    def reset(self) -> None:
        self._history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def _chat(self) -> dict:
        try:
            resp = requests.post(
                f"{self._host}/api/chat",
                json={
                    "model": self._model,
                    "messages": self._history,
                    "tools": self._tools,
                    "stream": False,
                },
                timeout=120,
            )
            resp.raise_for_status()
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(
                "Could not reach Ollama. Is it installed and running? "
                "Try 'ollama serve' in another terminal, and make sure you've "
                f"pulled the model with 'ollama pull {self._model}'."
            ) from exc
        return resp.json()

    def respond(self, user_text: str, ask_confirm) -> str:
        self._history.append({"role": "user", "content": user_text})

        # Cap tool-call rounds so a confused local model can't loop forever.
        for _ in range(6):
            data = self._chat()
            message = data.get("message", {})
            tool_calls = message.get("tool_calls") or []

            self._history.append(
                {"role": "assistant", "content": message.get("content", ""), **(
                    {"tool_calls": tool_calls} if tool_calls else {}
                )}
            )

            if not tool_calls:
                return (message.get("content") or "").strip() or "(no response)"

            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                raw_args = fn.get("arguments", {})
                # Ollama usually returns arguments already as a dict, but be
                # defensive in case a model emits a JSON string instead.
                if isinstance(raw_args, str):
                    try:
                        raw_args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        raw_args = {}

                confirm_fn = ask_confirm if name not in SAFE_TOOLS else (lambda _p: True)
                result_text = execute_tool(name, raw_args, confirm_fn)
                self._history.append(
                    {"role": "tool", "content": result_text, "name": name}
                )

        return (
            "I'm having trouble completing that with the local model — it kept "
            "trying tool calls without finishing. Try rephrasing, or switch "
            "JARVIS_BACKEND=anthropic in .env for a more capable model."
        )
