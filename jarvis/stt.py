"""
stt.py — Push-to-talk audio capture + local speech-to-text.

Privacy note: this module records audio only while the push-to-talk key is
held down (no always-on listening), and transcribes it locally with
faster-whisper. Raw audio is written to a temp WAV file for the duration of
one utterance and then deleted; nothing is uploaded anywhere by default.
"""

from __future__ import annotations

import os
import queue
import tempfile
import wave
from contextlib import contextmanager

import numpy as np
import sounddevice as sd

_SAMPLE_RATE = 16000
_CHANNELS = 1


class LocalWhisperSTT:
    def __init__(self, model_size: str | None = None):
        # Imported lazily so the rest of the app can run / be linted even if
        # faster-whisper's model files haven't been downloaded yet.
        from faster_whisper import WhisperModel

        model_size = model_size or os.getenv("JARVIS_WHISPER_MODEL", "base.en")
        # CPU by default for portability; set device="cuda" yourself if you
        # have a GPU and want lower latency.
        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe_wav(self, wav_path: str) -> str:
        segments, _info = self._model.transcribe(wav_path, language="en")
        return " ".join(seg.text.strip() for seg in segments).strip()


@contextmanager
def _record_while(should_continue) -> str:
    """Records audio to a temp WAV file for as long as `should_continue()`
    returns True. Yields the path, then deletes the file on exit."""
    q: queue.Queue = queue.Queue()

    def callback(indata, frames, time_info, status):  # noqa: ARG001
        q.put(indata.copy())

    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    frames = []
    with sd.InputStream(
        samplerate=_SAMPLE_RATE, channels=_CHANNELS, dtype="int16", callback=callback
    ):
        while should_continue():
            try:
                frames.append(q.get(timeout=0.1))
            except queue.Empty:
                continue

    audio = np.concatenate(frames, axis=0) if frames else np.zeros((0, _CHANNELS), dtype="int16")

    with wave.open(path, "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(2)  # int16
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(audio.tobytes())

    try:
        yield path
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def record_push_to_talk(should_continue) -> str:
    """Convenience wrapper returning the recorded WAV path via the context
    manager above. Caller is responsible for transcribing before the `with`
    block exits (the file is deleted on exit)."""
    return _record_while(should_continue)
