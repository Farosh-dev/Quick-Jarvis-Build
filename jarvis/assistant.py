"""
assistant.py — Main loop. Push-to-talk voice assistant:

    hold SPACE -> speak -> release SPACE -> transcribed locally ->
    PII guard checks the transcript -> (confirm if needed) ->
    sent to Claude (brain.py, with its own per-action confirmation) ->
    reply spoken back via TTS -> (optionally) redacted-logged

Run with:  python -m jarvis.assistant
Type-only mode (no mic/speakers needed):  python -m jarvis.assistant --text
"""

from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

from . import logging_utils, pii_guard

load_dotenv()


def _build_brain():
    """Picks the reasoning backend based on JARVIS_BACKEND in .env.
    Both backends implement the same respond(user_text, ask_confirm)
    interface and share the exact same tool guardrails (jarvis/tools.py)."""
    backend = os.getenv("JARVIS_BACKEND", "anthropic").lower()

    if backend == "ollama":
        from .brain_ollama import OllamaBrain

        return OllamaBrain()

    if backend != "anthropic":
        print(
            f"[warn] Unknown JARVIS_BACKEND={backend!r}, falling back to 'anthropic'.",
            file=sys.stderr,
        )

    from .brain import Brain

    if not os.getenv("ANTHROPIC_API_KEY"):
        print(
            "ERROR: JARVIS_BACKEND=anthropic requires ANTHROPIC_API_KEY. "
            "Set it in .env, or set JARVIS_BACKEND=ollama to use a free local "
            "model instead (see README.md).",
            file=sys.stderr,
        )
        sys.exit(1)

    return Brain()


def _ask_confirm(prompt: str) -> bool:
    """Confirmation gate used by both the PII guard and the brain's tool
    execution. Defaults to 'no' on anything but a clear yes."""
    answer = input(f"\n{prompt}").strip().lower()
    return answer in {"y", "yes", "confirm", "confirmed"}


def _run_text_mode(brain) -> None:
    print("JARVIS-lite (text mode). Type 'quit' to exit.\n")
    pii_enabled = os.getenv("JARVIS_PII_GUARD", "true").lower() == "true"

    while True:
        try:
            user_text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit"}:
            break

        text_to_send = user_text
        if pii_enabled:
            allowed, safe_or_original = pii_guard.guard_text(
                user_text, _ask_confirm, context="send this message to Claude"
            )
            if not allowed:
                print(
                    "\n[blocked] Not sending unmasked text. Sending the masked "
                    f"version instead: \"{safe_or_original}\"\n"
                )
            text_to_send = safe_or_original

        logging_utils.log("user", text_to_send)
        reply = brain.respond(text_to_send, _ask_confirm)
        logging_utils.log("assistant", reply)
        print(f"jarvis> {reply}\n")


def _run_voice_mode(brain) -> None:
    import threading

    from pynput import keyboard

    from . import stt, tts

    print("JARVIS-lite (voice mode). Hold SPACE to talk, release to send. Ctrl+C to quit.\n")

    stt_engine = stt.LocalWhisperSTT()
    tts_engine = tts.get_tts_backend()
    pii_enabled = os.getenv("JARVIS_PII_GUARD", "true").lower() == "true"

    recording = {"active": False}

    def handle_utterance():
        # Runs off the pynput listener thread so on_release can still fire
        # (a single pynput.Listener delivers press/release callbacks
        # sequentially on one thread, so blocking here would starve
        # on_release and "listening" would never end).
        with stt.record_push_to_talk(lambda: recording["active"]) as wav_path:
            while recording["active"]:
                pass
            text = stt_engine.transcribe_wav(wav_path)

        if not text:
            print("[heard nothing]\n")
            return

        print(f"you (voice)> {text}")

        text_to_send = text
        if pii_enabled:
            allowed, safe_or_original = pii_guard.guard_text(
                text, _ask_confirm, context="send this message to Claude"
            )
            if not allowed:
                print(f"[blocked] Sending masked version instead: \"{safe_or_original}\"")
            text_to_send = safe_or_original

        logging_utils.log("user", text_to_send)
        reply = brain.respond(text_to_send, _ask_confirm)
        logging_utils.log("assistant", reply)
        print(f"jarvis> {reply}\n")
        tts_engine.speak(reply)

    def on_press(key):
        if key == keyboard.Key.space and not recording["active"]:
            recording["active"] = True
            print("[listening...]")
            threading.Thread(target=handle_utterance, daemon=True).start()

    def on_release(key):
        if key == keyboard.Key.space:
            recording["active"] = False
        if key == keyboard.Key.esc:
            return False

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


def main() -> None:
    parser = argparse.ArgumentParser(description="JARVIS-lite voice assistant")
    parser.add_argument(
        "--text", action="store_true", help="Run in keyboard text mode instead of voice."
    )
    args = parser.parse_args()

    brain = _build_brain()

    if args.text:
        _run_text_mode(brain)
    else:
        _run_voice_mode(brain)


if __name__ == "__main__":
    main()
