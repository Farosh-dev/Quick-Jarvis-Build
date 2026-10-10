# JARVIS-lite — Stage 1

A minimal, privacy-conscious voice assistant: the first working stage on the
road to a JARVIS-style assistant. This stage is push-to-talk, runs
speech-to-text and text-to-speech **locally by default**, and uses Claude as
the reasoning core with hard confirmation gates around anything sensitive.

It is not "always-on, ambient, sees-and-hears-everything JARVIS" — that's a
later stage (see Roadmap). This stage is the trustworthy foundation to build
that on.

## What it does

1. Hold **Space**, speak, release **Space**.
2. Audio is transcribed **on your machine** (faster-whisper, no cloud call).
3. The transcript is scanned for likely PII (emails, phone numbers, card
   numbers, IDs, addresses, etc.). If found, you're shown a masked preview
   and asked to explicitly confirm before the unmasked text is sent
   anywhere.
4. The (possibly masked) text goes to Claude, which replies in short, speakable
   sentences.
5. If Claude wants to run a system action (currently: shell commands), it
   proposes the exact command and reason, and **waits for your explicit
   yes/no** before running it. Nothing executes silently.
6. The reply is spoken back to you via offline TTS.
7. Nothing is logged to disk unless you turn logging on, and even then only
   the redacted (PII-masked) version is ever written.

## Setup

```bash
git clone https://github.com/Farosh-dev/Quick-Jarvis-Build.git
cd Quick-Jarvis-Build
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env — see "Choosing a brain backend" below
```

## Choosing a brain backend

This project supports two interchangeable "brains," selected via
`JARVIS_BACKEND` in `.env`. Both share the exact same guardrails (PII guard,
command denylist, confirmation prompts) — the choice only affects answer
quality and where your text is processed.

| | `JARVIS_BACKEND=anthropic` (default) | `JARVIS_BACKEND=ollama` |
|---|---|---|
| Cost | Pay-per-token API billing (separate from a Claude Pro subscription — Pro does **not** include API credit) | Free, no API cost |
| Where text is processed | Anthropic's servers | Entirely on your machine |
| Reasoning / tool-use quality | Strong | Noticeably weaker; smaller local models sometimes garble or over-trigger tool calls |
| Setup | Just an API key + billing at console.anthropic.com | Install Ollama + pull a model (below) |

**To use the free local option:**

1. Install Ollama: https://ollama.com/download
2. Pull a tool-calling-capable model (pick one based on your RAM):
   ```bash
   ollama pull llama3.1:8b      # good default, needs ~8GB RAM
   # or: ollama pull qwen2.5:7b
   # or (lower-end machines): ollama pull llama3.2:3b
   ```
3. In `.env`:
   ```
   JARVIS_BACKEND=ollama
   OLLAMA_MODEL=llama3.1:8b
   ```
4. Make sure Ollama is running (`ollama serve`, or it's already running as a
   background service after install) before starting JARVIS-lite.

Because local models are more error-prone with tool calls, `jarvis/tools.py`
adds a hard, non-bypassable denylist (`jarvis/command_guard.py`) on top of
the existing confirmation prompt: commands matching dangerous patterns
(`sudo`, `rm -rf`, disk formatting, piping a download straight into a shell,
reading credential files, etc.) are refused automatically and never even
shown to you for approval — this applies to both backends, but matters more
here since a smaller model is more likely to propose something ill-advised.

You can switch backends any time by editing `JARVIS_BACKEND` in `.env` — no
code changes needed.

System dependencies:
- **macOS**: `brew install portaudio` (needed by `sounddevice`)
- **Linux**: `sudo apt install portaudio19-dev python3-dev espeak` (espeak backs pyttsx3)
- **Windows**: usually works out of the box; if pyttsx3 has issues, it uses SAPI5.

First run will download the local Whisper model (`base.en` by default, ~140MB)
— this happens once and is cached locally.

## Run it

Voice mode (needs a mic + speakers):

```bash
python -m jarvis.assistant
```

Text-only mode (no mic/speakers required — good for testing the guardrails
and Claude integration first):

```bash
python -m jarvis.assistant --text
```

Try it: type something with a fake email or phone number in text mode and
watch it get intercepted before it reaches Claude.

## Security / privacy model

This is the part you specifically asked for — here's exactly what's
implemented and what its limits are.

**PII guardrail (`jarvis/pii_guard.py`)**
- Runs entirely locally (regex-based), before any network call.
- Detects: emails, phone numbers, card numbers, US SSNs, Aadhaar-like
  12-digit IDs, IBAN/bank-account-like strings, IP addresses, DOB phrases,
  street addresses.
- On a match, the user sees a masked preview and must type/say an explicit
  "yes" — anything else (including no answer, "maybe", silence) is treated
  as "no" and only the masked version is used downstream.
- This is a heuristic, not a legal-grade PII classifier. It will miss
  cleverly obfuscated PII and will occasionally flag things that aren't PII
  (e.g. a 12-digit tracking number). Tune the patterns in `pii_guard.py` for
  your needs, and treat it as a speed bump, not a compliance certification.

**Action confirmation (`jarvis/tools.py`, shared by both backends)**
- Neither Claude nor a local Ollama model can execute anything on your
  machine directly — they can only *propose* a tool call.
- Every proposed `run_shell_command` first passes through a hard denylist
  (`jarvis/command_guard.py`) that blocks dangerous patterns outright —
  `sudo`/privilege escalation, `rm -rf`-style recursive deletes, disk
  formatting/partitioning, shutdown/reboot, piping a curl/wget download
  straight into a shell, reading SSH keys / AWS credentials / `.env` /
  `/etc/shadow`, fork bombs, and a few others. These are refused
  automatically and never even reach the confirmation prompt.
- Anything that clears the denylist still shows you the exact command and
  the model's stated reason, and requires explicit confirmation before it
  runs.
- Only genuinely side-effect-free tools (currently: reading the clock) skip
  confirmation entirely.
- Add new tools to `TOOLS` in `jarvis/tools.py` deliberately, and keep them
  out of `SAFE_TOOLS` unless they truly have no side effects. If a new tool
  can run arbitrary system commands, extend `command_guard.py`'s patterns
  accordingly.

**Local-first processing**
- STT runs on-device via faster-whisper; raw audio never leaves the machine
  and the temp WAV file is deleted immediately after transcription.
- TTS defaults to fully offline (`pyttsx3`). Cloud TTS (ElevenLabs) is
  opt-in only via `JARVIS_TTS_BACKEND=elevenlabs` in `.env`, and only the
  final response text (not your voice) would be sent to it.

**Logging**
- Off by default (`JARVIS_ENABLE_LOGGING=false`).
- When enabled, every line is redacted through the same PII scanner before
  being written to `logs/conversation.log` — even PII you explicitly
  approved sending to Claude for that turn is never written to disk in the
  clear.

**Secrets**
- API keys live only in `.env`, which is git-ignored. Never hardcode keys in
  source files, and never commit `.env`.

**What this does *not* protect against**
- Whatever you explicitly confirm sending still reaches Anthropic's API —
  this guardrail is about preventing *accidental* leakage, not stopping you
  from sharing data you've deliberately decided to share.
- It doesn't sandbox `run_shell_command` beyond the confirmation prompt — a
  confirmed malicious/careless command can still do damage. Treat the
  confirmation prompt as your last line of defense and read commands before
  approving them.
- It doesn't encrypt anything at rest beyond what your OS already does.

## Roadmap to a fuller JARVIS

This stage 1 is deliberately small so the guardrails could be reviewed
end-to-end. Suggested next stages, each additive:

1. **Wake word** — swap push-to-talk for an always-listening wake-word
   engine (e.g. OpenWakeWord/Porcupine) so you just say "Hey JARVIS." Keep
   the same PII/action guardrails downstream.
2. **Vision** — periodic or on-demand screenshots / webcam frames sent to a
   vision-capable Claude model, with the *same* confirm-before-send pattern
   for anything that looks like it contains sensitive on-screen content
   (extend `pii_guard.py` with an image-based check, or just always confirm
   before sending screenshots).
3. **More tools** — calendar, smart home (Home Assistant), browser control,
   file search — each added to `brain.py`'s `TOOLS` list, each defaulting to
   "requires confirmation" unless you deliberately mark it safe.
4. **Persistent memory** — a local (not cloud) store of facts JARVIS should
   remember between sessions, with the same "ask before storing anything
   that looks like PII" pattern.
5. **Multi-turn interruption / streaming** — stream Claude's response and
   start speaking before the full reply is generated, for lower perceived
   latency.

## Project layout

```
Quick-Jarvis-Build/
├── .env.example        # copy to .env and fill in your API key
├── requirements.txt
├── README.md
└── jarvis/
    ├── assistant.py      # main loop (voice + text modes), picks the backend
    ├── brain.py          # Claude (Anthropic API) backend
    ├── brain_ollama.py   # free, fully local open-source model backend
    ├── tools.py          # shared tool definitions + execution (both backends)
    ├── command_guard.py  # hard denylist for dangerous shell commands
    ├── pii_guard.py       # local PII detection/masking/confirmation
    ├── stt.py            # push-to-talk local speech-to-text
    ├── tts.py            # offline / optional cloud text-to-speech
    └── logging_utils.py   # opt-in, always-redacted logging
```
