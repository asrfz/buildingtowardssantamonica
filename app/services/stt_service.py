"""
stt_service -- ElevenLabs Scribe speech-to-text for HomePulse deaf-user input.

ElevenLabs track usage:
    Uses Scribe v1 model for high-accuracy transcription of spoken queries.
    Paired with the TTS voice agent so ElevenLabs handles BOTH input (Scribe)
    and output (eleven_turbo_v2_5 / eleven_flash_v2_5) for the full voice loop.

Input format:
    WAV bytes at 16 kHz, 16-bit mono -- produced by wake_word_service.py
    from the sounddevice capture stream.

Output:
    Plain-text transcript string. Returns empty string on failure so the
    caller can decide whether to retry or discard.
"""

import io
import logging
import wave
from typing import TYPE_CHECKING

from app.config import settings

logger = logging.getLogger(__name__)

_client = None  # lazy -- only init when API key is present


def _get_client():
    global _client
    if _client is None:
        from elevenlabs.client import ElevenLabs
        _client = ElevenLabs(api_key=settings.ELEVENLABS_API_KEY)
    return _client


def numpy_to_wav_bytes(audio_int16, sample_rate: int = 16000) -> bytes:
    """
    Convert a 16-bit mono numpy array to WAV bytes suitable for Scribe.
    Called in the capture thread -- no async, no I/O.
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)           # 16-bit = 2 bytes per sample
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    return buf.getvalue()


def transcribe_sync(wav_bytes: bytes) -> str:
    """
    Synchronous Scribe call -- runs in asyncio.to_thread from the agent.
    Returns transcript text, or "" on any error.
    """
    if not settings.ELEVENLABS_API_KEY.strip():
        logger.warning("[STT] ELEVENLABS_API_KEY not set -- transcription skipped")
        return ""

    try:
        client = _get_client()
        wav_file = io.BytesIO(wav_bytes)
        wav_file.name = "audio.wav"     # Scribe uses the filename to detect format

        result = client.speech_to_text.convert(
            file=wav_file,
            model_id="scribe_v1",
            language_code="en",
            tag_audio_events=False,     # skip non-speech event tagging
            timestamps_granularity="none",  # skip word timestamps -- faster
        )
        transcript = (result.text or "").strip()
        logger.info(f"[STT] Scribe transcript: {transcript!r}")
        return transcript

    except Exception as exc:
        logger.warning(f"[STT] Scribe error: {exc}")
        return ""


async def transcribe(wav_bytes: bytes) -> str:
    """Async wrapper -- offloads Scribe HTTP call to a thread."""
    import asyncio
    return await asyncio.to_thread(transcribe_sync, wav_bytes)
