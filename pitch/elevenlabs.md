# HomePulse × ElevenLabs — Track Pitch

## What We Built

HomePulse serves two user populations with fundamentally different needs: **elderly users** who need clear spoken alerts about home hazards, and **deaf users** who need a voice-in/text-out interface to ask questions about their home environment. ElevenLabs handles both directions — voice output via TTS and voice input via Scribe STT — making it the only voice SDK in the entire stack.

---

## Voice Output — Real-Time Safety Alerts

### Two-Model TTS Strategy

We use two ElevenLabs TTS models with different latency/quality tradeoffs, selected automatically based on context:

**`eleven_turbo_v2_5`** — Initial safety alerts. When a sensor anomaly is confirmed and the object's position has been determined, the first spoken alert is generated with the turbo model. Quality and naturalness matter here — the user is hearing something unexpected and alarming. We use warm, conversational language: *"Your water bottle fell to your left"* rather than a robotic beep.

**`eleven_flash_v2_5`** — Progressive correction ticks. Every 3 seconds, the system recaptures a webcam frame, asks Claude where the object and the user are now, and speaks a directional correction: *"A bit further to your right"*, *"You're getting closer."* Flash's ultra-low latency is critical here — a 3-second interval with a slow TTS model creates jarring pauses. Flash keeps the guidance feeling live.

```python
# tts_service.py — model selected by caller context
MODEL_ALERT      = "eleven_turbo_v2_5"
MODEL_CORRECTION = "eleven_flash_v2_5"

def speak(text: str, correction: bool = False) -> None:
    model = MODEL_CORRECTION if correction else MODEL_ALERT
    audio_bytes = b"".join(
        client.text_to_speech.convert(
            voice_id=settings.ELEVENLABS_VOICE_ID,
            text=text,
            model_id=model,
            output_format="mp3_22050_32",
            voice_settings=VoiceSettings(
                stability=0.70,
                similarity_boost=0.80,
                style=0.0,
                use_speaker_boost=True,
            ),
        )
    )
```

`convert()` returns an `Iterator[bytes]` — we consume it fully with `b"".join()` then play via pygame.mixer (no ffmpeg dependency on Windows).

### Spatial Guidance System

The voice agent doesn't just say "the stove is on." It guides users to what they need to address. The `spatial_service` module converts Claude vision's fractional bounding box coordinates into directional language, accounting for camera perspective (when the camera faces the user, left/right axes are inverted):

- *"Your water bottle fell to the left of you. Move to your left."*
- *"Keep going — a bit further right."*
- *"Good, you found it."*

This loop runs for up to 30 seconds (10 ticks × 3 seconds) or until the object disappears from the camera frame (assumed retrieved) or the user's position converges on the object's position.

---

## Voice Input — Deaf User Interface

### The Problem

Deaf users cannot hear safety alerts from the system. But they also cannot easily query the system — they can't call out to a voice assistant. HomePulse solves this with a wake-word-activated query system: the user speaks (they can speak, but not hear), the system transcribes using ElevenLabs Scribe, processes the question through the AI pipeline, and displays the answer as text on a real-time WebSocket overlay.

### ElevenLabs Scribe v1 for STT

The `stt_service` module wraps Scribe's `speech_to_text.convert()` API:

```python
def transcribe_sync(wav_bytes: bytes) -> str:
    wav_file = io.BytesIO(wav_bytes)
    wav_file.name = "audio.wav"
    result = client.speech_to_text.convert(
        file=wav_file,
        model_id="scribe_v1",
        language_code="en",
        tag_audio_events=False,
        timestamps_granularity="none",
    )
    return (result.text or "").strip()
```

We chose Scribe specifically because it keeps the entire voice stack inside ElevenLabs — TTS and STT from the same provider, single API key, consistent audio quality assumptions.

### Wake Word Detection Without Extra Libraries

Rather than adding Porcupine or another wake word SDK, we detect wake words by checking Scribe's transcript output for trigger phrases:

```
WAKE_WORDS = ["hey homepulse", "hey home pulse", "hey pulse", "hey program", "homepulse"]
```

If the transcript starts with (or contains) a wake word, the remaining text after the wake word is extracted as the query. This stays entirely within the ElevenLabs ecosystem and requires no additional API keys or keyword file registration.

### Audio Capture and VAD

`wake_word_service` uses `sounddevice` to stream 16kHz audio in 100ms chunks. A simple RMS energy VAD gate (threshold 400) determines speech boundaries — start recording when energy exceeds the threshold, stop after 1.2 seconds of silence (`SILENCE_CHUNKS=12`). The captured speech is packed into WAV bytes using Python's standard `wave` module and sent to Scribe.

The captured query is placed into a thread-safe queue that `voice_input_agent` drains every second, routing the query through the FetchAI agent network to `dashboard_agent` for Claude processing.

### Visual Response Overlay

When `dashboard_agent` returns the Claude-generated answer, `voice_input_agent` pushes it to a FastAPI WebSocket endpoint (`/voice/push`). All connected browser clients receive the transcript and answer in real-time:

```
User says: "Hey HomePulse, was the stove left on today?"
     ↓ Scribe STT
transcript: "was the stove left on today?"
     ↓ FetchAI message to dashboard_agent
     ↓ Claude + MongoDB events query
answer: "Yes, at 2:14 PM the stove was detected as on with no activity for 18 minutes. 
         Margaret turned it off after being notified."
     ↓ WebSocket push
[browser overlay shows transcript + answer simultaneously]
```

The deaf user sees their spoken question echoed back (so they know the system heard them) and the answer displayed as styled text — no audio needed anywhere in the response path.

---

## End-to-End ElevenLabs Coverage

| User action | ElevenLabs role |
|---|---|
| Sensor detects stove left on | Scribe STT transcription is *not* involved here — sensor data, not speech |
| Voice agent speaks initial alert | `eleven_turbo_v2_5` TTS — warm, natural delivery |
| Voice agent speaks directional correction | `eleven_flash_v2_5` TTS — ultra-low latency, 3s loop |
| User says "hey HomePulse, is everything ok?" | `scribe_v1` STT — wake word + query extraction |
| System answers the question as text | ElevenLabs Scribe enabled the input; TTS could also read the answer aloud |

ElevenLabs is the only audio technology in the stack. No pyttsx3, no gTTS, no Whisper, no Web Speech API.

---

## Why ElevenLabs Specifically

**Same ecosystem for TTS and STT.** One API key covers both directions. The mental model is consistent: send text, get natural speech. Send speech, get accurate text.

**Model granularity for latency vs. quality.** No other TTS provider gives this level of control at the model level — turbo for quality, flash for speed, selectable per call with no code restructuring. This was essential for the correction loop UX.

**Scribe's accuracy on conversational speech.** The queries from deaf users are natural language, often informal ("is the stove still on?", "what happened this morning?"). Scribe handles this without needing a custom vocabulary or acoustic model.

**Production-quality voice for vulnerable users.** The target users are elderly or deaf. A robotic TTS voice creates anxiety. ElevenLabs' natural voice quality makes the system feel like a caring assistant, not an alarm system — which is exactly the experience we designed for.
