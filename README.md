# HomePulse AI

**HomePulse** is a real-time home safety system for older adults living independently. Arduino sensors (temperature, sound, motion, magnetic, pressure) feed a **FastAPI** backend and a **Fetch.ai uAgents** bureau. **Anthropic Claude** handles triage, multimodal reasoning over camera evidence, alert copy, and scheduled digests. **MongoDB** stores users, events, baselines, zones, and learning data. **Cloudinary** hosts and crops vision frames; **ElevenLabs** powers TTS/STT for voice paths; **Gmail SMTP** sends alerts.

This README is written so a **Claude chat** (or any collaborator) can orient quickly, ship **Devpost** copy, and know where to edit code without reading the entire tree.

---

## Read this repository in order

| Order | File | Why |
|------|------|-----|
| 1 | `CONTEXT.md` | Product vision, stack, Arduino payload, rules |
| 2 | `STRUCTURE.md` | Folder map (some paths may lag; cross-check `app/`) |
| 3 | `AGENT_CONTEXT.md` | **Full sensor→notification pipeline**, coding rules, Claude touchpoints |
| 4 | `FLOW_AND_TESTING.md` | **Startup**, env, live testing, `/sensor/simulate`, Mongo simulation queue |
| 5 | `PITCH_CLAUDE.md` | Narrative for sponsors / Anthropic angle |
| 6 | `pitch/*.md` | Track-specific notes (MongoDB, Cloudinary, ElevenLabs, Fetch.ai, Anthropic) |

**Single source of truth for settings:** `app/config.py` (Pydantic `Settings` loads root `.env`).

---

## Quick start (local dev)

Use any Python environment you already use (virtualenv / conda / system Python is fine). Then:

```bash
pip install -r requirements.txt
# Configure .env at repo root (see below)
python scripts/register_agents.py   # paste output into agents/agent_messages.py
uvicorn app.main:app --reload --port 8000
python run_agents.py                # second terminal; bureau uses port 8002 by default
```

Optional UI:

```powershell
# Windows (from repo root)
.\scripts\start_frontend.ps1
```

```bash
# macOS / Linux
chmod +x scripts/start_frontend.sh && ./scripts/start_frontend.sh
```

Or manually: `cd frontend && npm install && npm run dev`

Details: **`FLOW_AND_TESTING.md`** (full checklist).

---

## Environment variables (summary)

Defined in **`app/config.py`**. Typical root `.env` keys:

- **MongoDB:** `MONGODB_URI`, `MONGODB_DB_NAME`
- **App:** `DEFAULT_USER_ID` (24-char hex ObjectId for the primary demo user), `APP_ENV` (`development` enables e.g. `GET /integration/dev-context`)
- **Claude:** `ANTHROPIC_API_KEY`
- **Fetch.ai:** `FETCHAI_AGENT_SEED`, `AGENTVERSE_KEY` (dashboard mailbox)
- **Cloudinary:** `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`; optional `CLOUDINARY_ALERT_THUMB_MAX_WIDTH`, `CLOUDINARY_NAMED_TRANSFORM_POSTCROP`, `CLOUDINARY_DESTROY_ON_FALSE_POSITIVE` (see **Cloudinary** below)
- **Gmail:** `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`
- **ElevenLabs:** `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`
- **Hardware:** `ARDUINO_SERIAL_PORT`, `ARDUINO_BAUD_RATE`, `WEBCAM_INDEX`

Frontend secrets use **`frontend/.env.local`** with the `VITE_` prefix only (see `frontend/.env.local.example`). Browsers do **not** load the root `.env`.

---

## Cloudinary

Each alert frame uploads **once** to `homepulse/raw/{event_id}`. The app builds **two HTTPS delivery URLs** from that `public_id` (full zone crop and a width-capped thumb)—no second stored object. Spelled out with anchors and ops notes in **`pitch/cloudinary.md`** (`#cloudinary-feature-index`).

**Features this repo uses**

| Area | What |
|------|------|
| Upload | In-memory JPEG, `public_id`, `resource_type=image`, `overwrite` where applicable |
| Tags | Comma-separated tags on every upload (e.g. `homepulse`, `alert`, `evt_*`, optional `uid_*`, `type_*`; previews/calibration use their own tag sets) |
| Layout | Namespaced `public_id` paths: raw alerts, `homepulse/snapshots/preview/…`, `homepulse/reference/calibration` |
| URLs | `secure_url` for the raw asset; `cloudinary.utils.cloudinary_url` for `cropped_image_url` and `cropped_thumb_url` |
| Crop | `c_crop` with **`fl_relative`** when vision returns 0–1 box; absolute pixels for calibrated zones |
| Full crop chain | Optional **named** post-crop transform (`CLOUDINARY_NAMED_TRANSFORM_POSTCROP`) **or** `e_sharpen:80` → `e_improve` → **`q_auto`** → **`f_auto`** → **`dpr_auto`** |
| Thumb chain | Same crop → sharpen → **`c_limit`** (max width from `CLOUDINARY_ALERT_THUMB_MAX_WIDTH`, default 480) → improve → q_auto → f_auto → dpr_auto |
| Lifecycle | `uploader.destroy` + **`invalidate=True`** on `homepulse/raw/{event_id}` when the user marks a false positive, if `CLOUDINARY_DESTROY_ON_FALSE_POSITIVE` is true |

**Code:** `app/services/cloudinary_service.py`.

---

## Architecture (mental model)

```
Arduino serial ─┐
                ├─► sensor_agent (math scoring) ─► triage_agent (Claude) ─┬─► history_agent ─┐
POST /sensor/simulate ─► Mongo sensor_simulation_queue ────────────────────┘                │
                (force_triage skips scoring → IrregularityEvent directly)                    │
                                                                                             ▼
                                                                              monitor_agent (Claude + image URL)
                                                                                             │
                                                                    escalation_agent → notification_agent (Claude email → Gmail)

Parallel: vision_agent (OpenCV, Cloudinary, optional VoiceAlert) ─► voice_agent (TTS + spatial ticks)

Sidecars: learning_agent, report_agent, heartbeat_agent, dashboard_agent (ASI:One), voice_input_agent (wake word → dashboard)
```

**Critical:** FastAPI and `run_agents.py` are **separate processes**. Simulated readings must land in **`sensor_simulation_queue`** (written by `POST /sensor/simulate`) so `sensor_agent` sees them. Optional JSON field **`force_triage`** sends a synthetic **`IrregularityEvent`** without baseline math (used by the frontend “Loud noise (full pipeline)” demo).

---

## Backend entry points

| Piece | Location |
|-------|-----------|
| FastAPI app | `app/main.py` |
| Routers | `app/routers/` — `sensor`, `events`, `users`, `zones`, `alerts`, `integration`, `dashboard`, `voice_ws`, `search`, `incidents` |
| Claude | `app/services/claude_service.py` only (agents must not import `anthropic` directly) |
| Agent bureau | `run_agents.py` imports all agents into one `Bureau` |

---

## Agents (Fetch.ai uAgents)

| Agent | File | Role |
|-------|------|------|
| sensor | `agents/sensor_agent.py` | Drain serial queue + **Mongo simulation queue**, score or force-send to triage |
| triage | `agents/triage_agent.py` | Claude: investigate yes/no |
| history | `agents/history_agent.py` | Mongo context → monitor |
| vision | `agents/vision_agent.py` | Webcam, zones, Cloudinary, **VoiceAlert** to voice_agent |
| monitor | `agents/monitor_agent.py` | Claude multimodal reasoning, writes events |
| escalation | `agents/escalation_agent.py` | Severity ladder |
| notification | `agents/notification_agent.py` | Claude email + Gmail |
| voice | `agents/voice_agent.py` | TTS + spatial guidance |
| voice_input | `agents/voice_input_agent.py` | STT + **`DASHBOARD_AGENT_ADDRESS`** |
| dashboard | `agents/dashboard_agent.py` | Agentverse chat; **`VOICE_INPUT_AGENT_ADDRESS`** for replies |
| learning / report / heartbeat | `agents/learning_agent.py`, `report_agent.py`, `heartbeat_agent.py` | Schedules + watchdog |

**Addresses:** run `python scripts/register_agents.py` and paste into **`agents/agent_messages.py`**. **`DASHBOARD_AGENT_ADDRESS`** must not stay empty for voice-input routing.

---

## Frontend (`frontend/`)

Vite + React **dev console**: sensor simulation (including **live demos**), events/search/incidents, dashboard chat probe, Cloudinary playground, optional WebSocket to `/voice/ws`.

- API base: `VITE_API_BASE`
- Optional duplicate user id: `VITE_DEFAULT_USER_ID`; otherwise in **development** the app calls **`GET /integration/dev-context`** for `DEFAULT_USER_ID`

---

## Testing

```bash
pytest
```

See **`FLOW_AND_TESTING.md`** for integration steps, curl examples, and Atlas search scripts.

---

## Devpost / demo cheat sheet (for Claude or humans)

**One-liner:** HomePulse combines **Arduino sensing**, **Claude reasoning** at triage/monitor/notify/report, **multi-agent orchestration** (Fetch.ai), **vision + Cloudinary**, and **caregiver alerts**—with **MongoDB** for memory and learning.

**Problem:** Independent aging + family anxiety; dumb thresholds and false alarms don’t scale.

**What to show live:** Start API + bureau → open frontend → **“Loud noise (full pipeline)”** → watch agent logs → **GET /events** for the seeded user → optional `/voice` or ASI:One if configured.

**Built with:** Python, FastAPI, Motor/MongoDB, uAgents, Anthropic Claude, Cloudinary, ElevenLabs, React/Vite, OpenCV, pyserial, Gmail SMTP.

**Honest constraints:** M0 Atlas FTS limits (search may fall back to regex); hardware demo needs serial + webcam; full email needs Gmail app password; Agentverse needs registration + tunnel for external chat.

---

## License / hackathon

Treat as team / hackathon codebase unless you add a formal license.
