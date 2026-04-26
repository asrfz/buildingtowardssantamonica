"""
tts_service — ElevenLabs text-to-speech for HomePulse voice guidance.

ElevenLabs track integration:
    Two models are used depending on urgency:

    eleven_flash_v2_5   — ultra-low latency (~75 ms first-byte), used for
                          progressive correction phrases where sub-second
                          response matters ("a little to your right")

    eleven_turbo_v2_5   — low latency with higher quality, used for the
                          initial event alert where a natural, warm delivery
                          is more important than raw speed ("your stove has
                          been left on and I can see it in front of you")

    Voice settings are tuned for clarity over character:
        stability=0.70       — consistent delivery, no unexpected variation
        similarity_boost=0.80 — stays true to the voice model
        style=0.0            — no style exaggeration; cleaner for directions
        use_speaker_boost    — enhanced presence for smart speaker output

Audio playback (Windows):
    ElevenLabs returns MP3 bytes. pygame.mixer handles local playback via SDL
    without requiring ffmpeg/mpv/afplay to be installed on the host machine.
    Audio is written to a NamedTemporaryFile then loaded by pygame.mixer.music;
    temp file is deleted immediately after playback completes.

Worker architecture:
    A single daemon thread owns the pygame mixer and drains a thread-safe
    queue of SpeechRequests. All coroutines call speak() or speak_async()
    which enqueue immediately and return — the event loop is never blocked.
"""

import io
import logging
import os
import queue
import tempfile
import threading
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)

# ── ElevenLabs model constants ────────────────────────────────────────────────
MODEL_ALERT      = "eleven_turbo_v2_5"   # warm, clear — initial event alerts
MODEL_CORRECTION = "eleven_flash_v2_5"   # ultra-low latency — correction loop

# Rachel voice — calm, warm, authoritative. Override with ELEVENLABS_VOICE_ID in .env.
_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"


@dataclass
class SpeechRequest:
    text: str
    model_id: str = MODEL_ALERT


# ── Internal queue + worker ───────────────────────────────────────────────────

_queue: queue.Queue[SpeechRequest | None] = queue.Queue()
_worker: threading.Thread | None = None
_ready = threading.Event()


def _play_mp3_bytes(audio_bytes: bytes) -> None:
    """Write MP3 bytes to a temp file and play via pygame.mixer (no ffmpeg needed)."""
    import pygame

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(50)
    finally:
        pygame.mixer.music.unload()
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _tts_worker() -> None:
    """
    Daemon thread: owns the pygame mixer and the ElevenLabs client for their
    full lifetime. Processes SpeechRequests sequentially so phrases never overlap.
    """
    no_api_key = not (settings.ELEVENLABS_API_KEY or "").strip()
    if no_api_key:
        logger.warning("[TTS] ELEVENLABS_API_KEY not set — voice guidance will only log, not play audio")
        _ready.set()
        while True:
            req = _queue.get()
            if req is None:
                break
            logger.info(f"[TTS] (no API key) would speak: {req.text[:120]}")
            _queue.task_done()
        return

    try:
        import pygame
        from elevenlabs.client import ElevenLabs
        from elevenlabs import VoiceSettings

        pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)

        client = ElevenLabs(api_key=settings.ELEVENLABS_API_KEY)
        voice_id = settings.ELEVENLABS_VOICE_ID or _DEFAULT_VOICE_ID

        voice_settings = VoiceSettings(
            stability=0.70,
            similarity_boost=0.80,
            style=0.0,
            use_speaker_boost=True,
        )

        _ready.set()
        logger.info("[TTS] ElevenLabs worker ready")

    except Exception as exc:
        logger.error(f"[TTS] Worker init failed: {exc}")
        _ready.set()
        return

    while True:
        req = _queue.get()
        if req is None:           # shutdown sentinel
            break

        try:
            # SDK 2.x: convert() always returns Iterator[bytes] — join into one buffer
            audio_bytes = b"".join(
                client.text_to_speech.convert(
                    voice_id=voice_id,
                    text=req.text,
                    model_id=req.model_id,
                    voice_settings=voice_settings,
                    output_format="mp3_22050_32",  # smallest MP3 — fast delivery
                )
            )

            _play_mp3_bytes(audio_bytes)
            logger.debug(f"[TTS] spoke: {req.text[:60]}")

        except Exception as exc:
            logger.warning(f"[TTS] ElevenLabs speak failed: {exc}")

        finally:
            _queue.task_done()


def _ensure_worker() -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_tts_worker, daemon=True, name="homepulse-tts")
        _worker.start()
        _ready.wait(timeout=8.0)


# ── Public API ────────────────────────────────────────────────────────────────

def speak(text: str, *, correction: bool = False) -> None:
    """
    Enqueue a phrase for TTS playback. Non-blocking — returns before audio plays.

    correction=True  →  eleven_flash_v2_5 (ultra-low latency, correction loop)
    correction=False →  eleven_turbo_v2_5 (higher quality, initial alerts)
    """
    _ensure_worker()
    model = MODEL_CORRECTION if correction else MODEL_ALERT
    logger.info(f"[TTS] queued ({'flash' if correction else 'turbo'}): {text}")
    _queue.put(SpeechRequest(text=text, model_id=model))


async def speak_async(text: str, *, correction: bool = False) -> None:
    """Async alias for speak(). Safe to call from any coroutine."""
    speak(text, correction=correction)


def stop_all() -> None:
    """Drain the speech queue (e.g. when a correction resolves mid-phrase)."""
    while not _queue.empty():
        try:
            _queue.get_nowait()
            _queue.task_done()
        except queue.Empty:
            break
    try:
        import pygame
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
    except Exception:
        pass
