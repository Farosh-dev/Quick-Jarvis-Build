"""
tts.py — Text-to-speech backends.

Default backend ("local") uses pyttsx3, which runs fully offline via the
OS's own speech engine — the assistant's spoken replies never leave the
machine. An optional "elevenlabs" backend is provided for a more natural
voice, but it is opt-in only (JARVIS_TTS_BACKEND=elevenlabs) because it
sends response text to a third-party cloud API.
"""

from __future__ import annotations

import os


class LocalTTS:
    """Fully offline TTS via pyttsx3."""

    def __init__(self):
        import pyttsx3

        self._engine = pyttsx3.init()

    def speak(self, text: str) -> None:
        self._engine.say(text)
        self._engine.runAndWait()


class ElevenLabsTTS:
    """Cloud TTS. Only instantiated if the user explicitly opts in via
    JARVIS_TTS_BACKEND=elevenlabs, since this sends text to a third party."""

    def __init__(self):
        api_key = os.getenv("ELEVENLABS_API_KEY")
        voice_id = os.getenv("ELEVENLABS_VOICE_ID")
        if not api_key or not voice_id:
            raise RuntimeError(
                "JARVIS_TTS_BACKEND=elevenlabs requires ELEVENLABS_API_KEY and "
                "ELEVENLABS_VOICE_ID to be set in .env"
            )
        from elevenlabs.client import ElevenLabs

        self._client = ElevenLabs(api_key=api_key)
        self._voice_id = voice_id

    def speak(self, text: str) -> None:
        import sounddevice as sd
        import numpy as np
        import io
        import soundfile as sf

        audio_stream = self._client.text_to_speech.convert(
            voice_id=self._voice_id, text=text, model_id="eleven_turbo_v2_5"
        )
        audio_bytes = b"".join(audio_stream)
        data, samplerate = sf.read(io.BytesIO(audio_bytes))
        sd.play(np.asarray(data), samplerate)
        sd.wait()


def get_tts_backend():
    backend = os.getenv("JARVIS_TTS_BACKEND", "local").lower()
    if backend == "elevenlabs":
        return ElevenLabsTTS()
    return LocalTTS()
