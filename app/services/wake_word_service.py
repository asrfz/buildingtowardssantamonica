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
import urllib.error
import urllib.request

import numpy as np

from app.services.stt_service import transcribe_sync, numpy_to_wav_bytes

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

# ── Wake words (checked against normalized transcript; order longest-first in logic) ──
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

_VOICE_PUSH_URL = "http://127.0.0.1:8000/voice/push"


def _normalize_for_wake(s: str) -> str:
    """Lowercase, drop commas/semicolons, collapse whitespace — matches STT variants."""
    x = s.lower().strip()
    x = re.sub(r"[,;]", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x


def _push_wake_ack() -> None:
    """Immediate UI feedback so the wake phrase feels responsive (sync, best-effort)."""
    try:
        payload = json.dumps(
            {
                "type": "wake_ack",
                "text": "Wake phrase heard — sending your request to HomePulse.",
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            _VOICE_PUSH_URL,
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


# ── Internal helpers ──────────────────────────────────────────────────────────

def _rms(chunk: np.ndarray) -> float:
    return float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))


def _extract_query(transcript: str) -> str | None:
    """
    Strip the wake word from the start of a transcript and return the question.
    Returns None if no wake word is found or nothing follows it.
    """
    lower = transcript.lower().strip()
    for wake in WAKE_WORDS:
        if lower.startswith(wake):
            question = transcript[len(wake):].strip().lstrip(",. ")
            return question if question else "What is happening at home right now?"
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
                    audio = np.concatenate(speech_chunks)
                    wav_bytes = numpy_to_wav_bytes(audio, SAMPLE_RATE)
                    # Transcribe synchronously on callback thread (100ms budget is fine
                    # since Scribe roundtrip << next callback gap for short phrases)
                    transcript = transcribe_sync(wav_bytes)
                    query = _extract_query(transcript)
                    if query:
                        logger.info(f"[WakeWord] Query detected: {query!r} (raw STT: {transcript!r})")
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
                f"[WakeWord] Listening... say one of: {WAKE_WORDS} followed by your question"
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
