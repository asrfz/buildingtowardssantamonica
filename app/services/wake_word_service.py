"""
wake_word_service -- Continuous audio capture with energy-based VAD and
wake-word detection for HomePulse deaf-user voice input.

Pipeline per utterance:
    sounddevice InputStream
      -> 100ms chunks fed into a numpy RMS energy gate (VAD)
      -> speech detected: accumulate chunks until 1s of silence
      -> accumulated audio -> stt_service.transcribe_sync (ElevenLabs Scribe)
      -> if transcript starts with a wake word: extract question, put in queue

Design notes:
    - Runs entirely on a single daemon thread; never touches the event loop.
    - The detected query queue is polled by voice_input_agent's on_interval.
    - Energy threshold (SPEECH_RMS_THRESHOLD) may need tuning for the room.
      A quieter mic needs a lower value; a noisy room needs a higher one.
    - Wake words are checked on the TRANSCRIPT, not raw audio, so no separate
      hotword model is needed. Scribe processes the full utterance first.
"""

import json
import logging
import queue
import re
import threading
import time
import urllib.error
import urllib.request

import numpy as np

from app.config import settings
from app.services.stt_service import transcribe_sync, numpy_to_wav_bytes
from app.services.tts_service import should_suppress_voice_capture

logger = logging.getLogger(__name__)

# ── Audio capture config ──────────────────────────────────────────────────────
SAMPLE_RATE      = 16000   # Hz -- Scribe works well at 16kHz
CHUNK_MS         = 100     # ms per capture chunk
CHUNK_SAMPLES    = int(SAMPLE_RATE * CHUNK_MS / 1000)   # 1600 samples / chunk

# ── VAD tuning ────────────────────────────────────────────────────────────────
SPEECH_RMS_THRESHOLD = 400    # int16 RMS -- raise if too many false triggers
SILENCE_CHUNKS       = 12     # 12 x 100ms = 1.2 s of quiet -> end of utterance
MIN_SPEECH_CHUNKS    = 4      # at least 400ms of speech before processing
MAX_SPEECH_CHUNKS    = 80     # cap at 8 s to prevent runaway recordings

# ── Wake words (checked against normalized transcript; longest matched first) ──
WAKE_WORDS = [
    "hey homepulse",
    "hey home pulse",
    "hey, home pulse",
    "hey, homepulse",
    "hi home pulse",
    "hi homepulse",
    "ok homepulse",
    "ok home pulse",
    "hey pulse",
    "hey program",
    "homepulse",
]

# Scribe often hears "pulse" as posts / hosts / pul… — match without making the user re-say it 5 times.
_WAKE_FUZZY = (
    # hey|hi|hello|ok|yo + home + (pulse | post(s) | Scribe corruptions)
    r"^(?:hey|hi|hello|ok|yo)[,\s]+home\s+(?:pulse|post|posts|pul\w{0,4}|host\w{0,3})\b",
    r"^(?:hey|hi|hello|ok|yo)[,\s]+homepulse\b",
    # "hey, pulse" / "hi pulse" (drops "home")
    r"^(?:hey|hi|hello|ok|yo)[,\s]+(?:home\s+)?(?:pulse|post|posts)\b",
    # Just "home pulse" / "home post" (two words)
    r"^home\s+(?:pulse|post|posts|pul\w{0,4}|host\w{0,3})\b",
    r"^homepulse\b",
)
_WAKE_FUZZY_COMPILED = [re.compile(p, re.I) for p in _WAKE_FUZZY]


def _voice_push_url() -> str:
    return f"{settings.HOMEPULSE_API_BASE.rstrip('/')}/voice/push"


def _normalize_for_wake(s: str) -> str:
    """Lowercase, drop commas/semicolons, collapse whitespace — matches STT variants."""
    x = s.lower().strip()
    x = re.sub(r"[,;]", " ", x)
    # "Hey, home post. What are …" in one utterance — merge clause break so wake regex sees one phrase.
    x = re.sub(
        r"\.\s+(?=(?:what|who|when|where|why|how|give|tell|show|list|can|could|would|should|"
        r"is|are|was|were|do|does|did|have|has|please|send|any|i\b|my|the|a\b|some|"
        r"um\b|uh\b)\b)",
        " ",
        x,
        flags=re.I,
    )
    x = re.sub(r"\s+", " ", x).strip()
    # Scribe often ends short phrases with "." — don't treat that as a follow-up "question"
    x = re.sub(r"[.?!…]+$", "", x).strip()
    return x


def _push_wake_ack() -> None:
    """Immediate UI feedback so the wake phrase feels responsive (sync, best-effort)."""
    try:
        payload = json.dumps(
            {
                "type": "wake_ack",
                "text": "Wake phrase heard.",
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            _voice_push_url(),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2.0)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        pass

# ── Shared query queue (voice_input_agent drains this) ───────────────────────
detected_query_queue: queue.Queue[str] = queue.Queue()

_listener_thread: threading.Thread | None = None
_stop_event = threading.Event()

# After a greeting or assistant answer, accept one or more utterances without the wake phrase.
FOLLOWUP_WINDOW_SECONDS = 22.0
_followup_deadline: float = 0.0


def arm_voice_followup_window() -> None:
    """Extend the window where STT text is treated as a question without saying the wake word."""
    global _followup_deadline
    _followup_deadline = time.monotonic() + FOLLOWUP_WINDOW_SECONDS


# ── Internal helpers ──────────────────────────────────────────────────────────

def _rms(chunk: np.ndarray) -> float:
    return float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))


def _wake_phrase_end(norm: str) -> int | None:
    """Length of wake prefix in normalized (lowercase) text, or None."""
    for wake in sorted(WAKE_WORDS, key=len, reverse=True):
        if norm.startswith(wake):
            return len(wake)
    for cre in _WAKE_FUZZY_COMPILED:
        m = cre.match(norm)
        if m:
            return m.end()
    return None


def _extract_query(transcript: str) -> str | None:
    """
    Strip the wake word from the start of a transcript and return the question.
    Returns None if no wake word is found (unless inside follow-up window).
    Returns \"\" if the user only said the wake phrase (greeting-only — no default recap question).
    """
    raw = transcript.strip()
    if not raw:
        return None
    norm = _normalize_for_wake(raw)
    wake_end = _wake_phrase_end(norm)
    if wake_end is not None:
        return norm[wake_end:].strip().lstrip(",. ")
    now = time.monotonic()
    if now < _followup_deadline:
        return raw
    return None


def _listen_loop() -> None:
    """
    Runs on a daemon thread for the process lifetime.
    Captures audio, gates on energy, transcribes on silence, emits queries.
    """
    try:
        import sounddevice as sd
    except ImportError:
        logger.error("[WakeWord] sounddevice not installed -- pip install sounddevice")
        return

    logger.info("[WakeWord] Listener thread started")

    state = "idle"          # "idle" | "recording"
    speech_chunks: list[np.ndarray] = []
    silence_count = 0

    def _callback(indata, frames, time_info, status):
        nonlocal state, speech_chunks, silence_count
        chunk = indata[:, 0].copy()   # mono from first channel

        energy = _rms(chunk)

        if state == "idle":
            if should_suppress_voice_capture():
                return
            if energy > SPEECH_RMS_THRESHOLD:
                state = "recording"
                speech_chunks = [chunk]
                silence_count = 0
                logger.debug(f"[WakeWord] Speech start (RMS={energy:.0f})")

        elif state == "recording":
            speech_chunks.append(chunk)

            if energy < SPEECH_RMS_THRESHOLD:
                silence_count += 1
            else:
                silence_count = 0

            # Utterance ended: 1.2s of silence, or max length hit
            if silence_count >= SILENCE_CHUNKS or len(speech_chunks) >= MAX_SPEECH_CHUNKS:
                if len(speech_chunks) >= MIN_SPEECH_CHUNKS:
                    if should_suppress_voice_capture():
                        logger.debug("[WakeWord] Dropping utterance — TTS playing or tail cooldown")
                    else:
                        audio = np.concatenate(speech_chunks)
                        wav_bytes = numpy_to_wav_bytes(audio, SAMPLE_RATE)
                        # Transcribe synchronously on callback thread (100ms budget is fine
                        # since Scribe roundtrip << next callback gap for short phrases)
                        transcript = transcribe_sync(wav_bytes)
                        query = _extract_query(transcript)
                        if query is not None:
                            if query.strip():
                                logger.info(f"[WakeWord] Query detected: {query!r} (raw STT: {transcript!r})")
                            else:
                                logger.info(f"[WakeWord] Wake only (no question yet) raw STT: {transcript!r}")
                            _push_wake_ack()
                            detected_query_queue.put(query)
                        elif transcript:
                            logger.info(f"[WakeWord] No wake word in transcript: {transcript!r}")

                speech_chunks = []
                silence_count = 0
                state = "idle"

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=CHUNK_SAMPLES,
            callback=_callback,
        ):
            logger.info(
                "[WakeWord] Listening... say a wake phrase to start, then your question — "
                "or ask another question within %.0fs after HomePulse replies without repeating the wake phrase.",
                FOLLOWUP_WINDOW_SECONDS,
            )
            _stop_event.wait()   # block until stop() is called
    except Exception as exc:
        logger.error(f"[WakeWord] InputStream error: {exc}")


# ── Public API ────────────────────────────────────────────────────────────────

def start() -> None:
    """Start the background listener thread. Safe to call multiple times."""
    global _listener_thread
    if _listener_thread and _listener_thread.is_alive():
        return
    _stop_event.clear()
    _listener_thread = threading.Thread(
        target=_listen_loop,
        daemon=True,
        name="homepulse-wake-word",
    )
    _listener_thread.start()


def stop() -> None:
    """Signal the listener thread to exit cleanly."""
    _stop_event.set()
