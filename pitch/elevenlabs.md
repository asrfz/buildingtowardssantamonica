# HomePulse × ElevenLabs — Track Pitch

## ElevenLabs feature index {#elevenlabs-feature-index}

| ID | Feature | Where |
|----|---------|--------|
| [feat-tts-stream](#feat-tts-stream) | **Text-to-speech** — `text_to_speech.convert`, MP3 `mp3_22050_32` | `app/services/tts_service.py` |
| [feat-tts-models](#feat-tts-models) | **Two models** — `eleven_turbo_v2_5` (alerts), `eleven_flash_v2_5` (corrections) | `tts_service` |
| [feat-voice-settings](#feat-voice-settings) | **VoiceSettings** — stability, similarity, style, speaker boost | `tts_service` |
| [feat-voice-id](#feat-voice-id) | **Configurable voice** — `ELEVENLABS_VOICE_ID` (default Rachel) | `app/config.py`, `tts_service` |
| [feat-stt-scribe](#feat-stt-scribe) | **Speech-to-text** — Scribe `speech_to_text.convert`, `scribe_v1` | `app/services/stt_service.py` |
| [feat-stt-wav](#feat-stt-wav) | **16 kHz mono WAV** input from mic pipeline | `stt_service`, `wake_word_service` |
| [feat-playback-worker](#feat-playback-worker) | **Background worker thread** — queue + pygame mixer (no ffmpeg on Windows) | `tts_service` |
| [feat-stt-suppress](#feat-stt-suppress) | **TTS ↔ STT coordination** — suppress mic during playback + tail cooldown | `should_suppress_voice_capture`, `TTS_STT_TAIL_COOLDOWN_SEC` |

---

## What we built {#what-we-built}

HomePulse serves two overlapping needs: **spoken safety guidance** (especially for users who benefit from hearing clear, calm directions) and **voice-in / text-out** access (e.g. deaf users who speak a question and read the answer on screen). **ElevenLabs is the only third-party voice stack**: **TTS** for output and **Scribe** for input—**one API key** (`ELEVENLABS_API_KEY`), consistent audio assumptions, no parallel Whisper/pyttsx3/Web Speech dependency in the core path.

---

## Architecture: how ElevenLabs fits the codebase {#architecture}

### TTS service (`tts_service.py`) {#feat-tts-stream}

- **Public API:** **`speak(text, correction=False)`** and **`speak_async(...)`** (async wrappers used by **`monitor_agent`**, **`voice_agent`**, etc.).
- **Queue + worker:** A **daemon thread** owns the **`ElevenLabs` client** and **pygame.mixer**. Coroutines **enqueue** and return immediately—the **uAgents / asyncio loop is not blocked** waiting on MP3 generation or speaker drain.
- **Output:** SDK **`text_to_speech.convert`** returns an **iterator of MP3 chunks**; we **`b"".join`** then write a **NamedTemporaryFile** and play via pygame (documented choice for **Windows-friendly** playback without ffmpeg).
- **No key:** Worker stays alive but **logs** lines instead of calling the API—demos degrade gracefully.

### Model selection (`correction` flag) {#feat-tts-models}

| Mode | Model | Use case |
|------|--------|----------|
| `correction=False` | **`eleven_turbo_v2_5`** | First alert after **`VoiceAlert`** / monitor summary—**warmer, clearer** delivery when the user is startled. |
| `correction=True` | **`eleven_flash_v2_5`** | **~3s** spatial correction loop in **`voice_agent`**—**low latency** so guidance feels continuous. |

Constants: **`MODEL_ALERT`**, **`MODEL_CORRECTION`** in `tts_service.py`.

### Voice identity {#feat-voice-id}

Default voice ID matches **Rachel** (`21m00Tcm4TlvDq8ikWAM`). Override with **`ELEVENLABS_VOICE_ID`** in `.env` for brand or locale experiments without code changes.

### Voice settings {#feat-voice-settings}

Tuned for **clarity and consistency** (higher stability, moderate similarity, `style=0`, `use_speaker_boost=True`) so directional phrases (“to your left”) stay intelligible on laptop speakers.

### STT service (`stt_service.py`) {#feat-stt-scribe}

- **`transcribe_sync(wav_bytes)`** — builds **`ElevenLabs`** client lazily, calls **`speech_to_text.convert`** with **`model_id="scribe_v1"`**, **`language_code="en"`**, no word timestamps (`timestamps_granularity="none"`) for speed.
- **`transcribe(wav_bytes)`** — **`asyncio.to_thread`** wrapper so agents don’t block the event loop on HTTP.
- **Empty API key** → warning + **`""`** transcript; callers skip routing.

### Audio format in {#feat-stt-wav}

**`wake_word_service`** captures **16 kHz, 16-bit mono** chunks via **sounddevice**; **`numpy_to_wav_bytes`** wraps them as **WAV** for Scribe’s **`file=`** upload.

### Avoiding speaker bleed into the mic {#feat-stt-suppress}

**`register_tts_playback_finished`**, **`should_suppress_voice_capture`**, **`TTS_STT_TAIL_COOLDOWN_SEC`**: while TTS plays and briefly after, the wake-word path can **drop** captures so **Scribe** does not transcribe the assistant’s own voice from the room.

---

## Voice output — real-time safety {#voice-output}

### Integration points

- **`voice_agent`** — After **`VoiceAlert`**, speaks the initial line (**turbo**), then **`on_interval`** ticks: OpenCV → JPEG base64 → Claude locate → **`spatial_service`** → short phrases (**flash**, `correction=True`). Uses **`stop_all`** when resolving mid-phrase.
- **`monitor_agent`** — **`speak_async`** on the post-reasoning alert string (optional TTS for the bureau machine).

### Spatial guidance

**`spatial_service`** turns fractional boxes into natural language (including camera **left/right** inversion where configured). ElevenLabs **does not** do spatial logic—it **renders** the strings the pipeline generates.

---

## Voice input — deaf-user and hands-busy queries {#voice-input}

### Pipeline

1. **`wake_word_service`** — RMS **VAD**, utterance bounds, WAV build → **`transcribe_sync`** (Scribe).
2. **Wake phrases** — Substring match on transcript (e.g. “hey homepulse”, “hey program”)—**no extra wake-word SDK**.
3. **`voice_input_agent`** — Drains queue, sends **`VoiceQuery`** to **`dashboard_agent`** (Fetch.ai).
4. **`VoiceQueryResponse`** — **`POST /voice/push`** → WebSocket clients show **transcript + answer** (text-first response path).

ElevenLabs **Scribe** enables **voice-in**; the **answer** is primarily **text on screen** (TTS for the answer is optional product-wise).

---

## End-to-end coverage {#coverage}

| User / system action | ElevenLabs role |
|----------------------|-----------------|
| Sensor → monitor reasoning | Optional **turbo** TTS for spoken alert |
| Vision → **`VoiceAlert`** → correction loop | **Turbo** then **flash** TTS |
| User speaks wake phrase + question | **Scribe** STT |
| Dashboard returns answer | Scribe enabled input; overlay shows text |

**Principle:** One vendor for **both** directions simplifies keys, billing, and latency debugging (`scripts/test_voice_pipeline.py` exercises TTS and full pipeline when keys and hardware are present).

---

## Configuration {#config}

| Variable | Purpose |
|----------|---------|
| **`ELEVENLABS_API_KEY`** | Required for real TTS/STT; empty → log-only TTS, skipped STT |
| **`ELEVENLABS_VOICE_ID`** | Optional override for TTS voice |

---

## Why ElevenLabs specifically {#why-elevenlabs}

**One ecosystem for TTS and STT** — Single key and consistent API surface for **`voice_agent`** and **`voice_input_agent`**.

**Model choice per utterance** — **Turbo vs flash** is a **parameter**, not a forked integration—critical for the **3-second** correction UX.

**Scribe on conversational queries** — Natural questions (“was the stove on?”) without maintaining a custom STT vocabulary.

**Voice quality for vulnerable users** — Natural TTS reduces **alarm fatigue** and anxiety versus robotic system speech; settings prioritize **clarity** over theatrics.

**Operational fit** — MP3 stream consumption + temp file + pygame matches **local bureau** deployment (laptop + mic + speakers) without chaining external media binaries.

---

## Operator pointers {#operators}

- **`FLOW_AND_TESTING.md`** — mic, `sounddevice`, **`DASHBOARD_AGENT_ADDRESS`** for full voice-query routing.
- **`python scripts/test_voice_pipeline.py`** — staged tests including ElevenLabs TTS and optional full webcam pipeline.
