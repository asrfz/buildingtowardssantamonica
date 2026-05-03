# HomePulse AI

> **Intelligent home safety monitoring for older adults — powered by multi-agent AI, real-time sensor reasoning, and warm voice alerts.**

Built at **LAHacks 2026** for the Anthropic, Fetch.ai, ElevenLabs, MongoDB, and Cloudinary tracks.

---

## What it does

HomePulse watches over an older adult living independently. It listens for hazards — a stove left on at 3 AM, an unusual sound, a suspected fall — and uses a chain of AI agents to decide whether something is genuinely wrong before contacting a caregiver. No false alarms crying wolf. No jargon in the email. Just the right message, to the right person, at the right time.

**For the resident:** live independently with dignity. Hazards are caught before they escalate.

**For the family:** peace of mind without daily check-in calls. Alerts arrive only when something actually matters.

**For the system:** real-world sensor data feeds a multi-agent AI pipeline that reasons about context — the same temperature spike at 7 PM during dinner is completely normal; at 3 AM it is not.

---

## The problem with existing solutions

| Approach | Problem |
|---|---|
| Nursing home | Expensive, removes independence |
| Manual check-ins | Inconsistent, burden on family |
| Basic smart home | Dumb thresholds, constant false alarms |
| Generic AI assistant | Not purpose-built for safety, no escalation logic |

HomePulse adds genuine reasoning. It knows the user's behavioral patterns, time of day, and false-positive history before it decides to alert anyone.

---

## Architecture overview

```
Arduino Sensors (every 5s)
        │  light · sound · motion · gyro · magnetics
        ▼
  sensor_agent ──────────────────────────────────────────────────────────────┐
  (anomaly scoring — pure math vs learned baseline)                          │
        │ IrregularityEvent                                                  │
        ▼                                                             POST /sensor/simulate
  triage_agent  ◄─── Claude: "Is this worth investigating?"                  │
  (early noise rejection — stops ~40% of anomalies here)                    │
        │ TriageResult                                                       │
        ├──────────────────────────────────────────────────┐                │
        ▼                                                   ▼                │
  history_agent                                       vision_agent           │
  (MongoDB: last 10 events,                           (OpenCV frame capture  │
   false positive rate,                                Claude vision: locate  │
   behavioral schema)                                 objects in scene       │
        │ UserHistoryContext                           Cloudinary: store &    │
        │                                             crop delivery URL)     │
        └──────────────────────┬───────────────────────────┘                │
                               ▼                                             │
                         monitor_agent ◄─── Claude multimodal reasoning      │
                         (sensor + image + history + time of day)            │
                               │ MonitorDecision                             │
                               ▼                                             │
                       escalation_agent                                      │
                       (severity ladder: LOW → MEDIUM → HIGH → CRITICAL)    │
                               │ EscalationOrder                            │
                               ▼                                             │
                    notification_agent ◄─── Claude: write warm email body    │
                    (Gmail SMTP → user + emergency contacts)                 │
                               │ optional 60s cancel window                 │
                               ▼                                             │
                       voice_agent (ElevenLabs TTS)                         │
                       spatial guidance if vision detects hazard location    │

Sidecars running in parallel:
  learning_agent   — every 24h: refresh baselines, tighten thresholds on confirmed events
  report_agent     — every 7d: Claude writes weekly digest email to family
  heartbeat_agent  — every 60s: watchdog; fires "sensor offline" alert if silent >2min
  dashboard_agent  — Agentverse Chat Protocol / ASI:One inbox
  voice_input_agent — ElevenLabs Scribe STT; wake-word → dashboard_agent → WebSocket → UI
```

**Key design choice:** FastAPI and the agent bureau are **separate processes**. They share state via MongoDB — agents drain a `sensor_simulation_queue` collection, write event documents, and read behavioral schemas. Nothing shared in memory.

---

## Tech stack

| Layer | Technology | Role |
|---|---|---|
| Hardware | Arduino + LSM9DS1 IMU + PDM mic | Light, sound, motion, gyro, magnetic readings |
| Serial bridge | pyserial (9600 baud) | Stream Arduino JSON to sensor_agent |
| Agent orchestration | Fetch.ai uAgents + Agentverse | 12 specialized agents, Bureau, Chat Protocol |
| REST backend | FastAPI + Uvicorn | Sensor ingest, events, users, zones, WebSocket |
| Database | MongoDB (Motor async) | Events, users, baselines, behavioral schema, learning data |
| AI reasoning | Anthropic Claude Sonnet 4.6 | Triage, multimodal vision analysis, email copy, weekly digest |
| Computer vision | OpenCV | Webcam frame capture on alert trigger |
| Image CDN | Cloudinary | Store raw frame; build cropped + enhanced delivery URLs |
| Voice output | ElevenLabs TTS (turbo/flash) | Warm voice alerts for resident |
| Voice input | ElevenLabs Scribe STT | Wake word detection, voice cancel window |
| Email | Gmail SMTP | Caregiver alert delivery |
| Frontend | React 19 + Vite + TypeScript | Dev console + caregiver dashboard |

---

## Claude — where AI reasoning lives

Claude is **not** called on raw sensor streams. That would be expensive and slow. Instead it sits at five high-value decision points:

| Agent | What Claude decides | Tokens |
|---|---|---|
| `triage_agent` | Is this anomaly worth investigating, given the time of day and baseline? | ~200 |
| `vision_agent` | What objects are visible in the frame and where (bounding boxes)? | ~200 |
| `monitor_agent` | Given sensor data + image + user history: what happened, how serious? | ~400 |
| `notification_agent` | Write a warm, plain-English email body (no jargon for elderly users) | ~800 |
| `report_agent` | Summarize this week's events into a readable family digest | ~600 |

All Anthropic API calls are centralized in **`app/services/claude_service.py`**. Agents never import `anthropic` directly — they call service functions that return typed Python objects.

**Example triage call:**
```python
result = await triage_event(
    event_type="SOUND_ANOMALY",
    sensor_payload=reading,
    deviation_score=2.8,
    hour_of_day=3,
    false_positive_rate=0.15
)
# {"investigate": true, "confidence": 0.91, "reason": "Loud sound at 3am is unusual..."}
```

**Example monitor call (multimodal):**
```python
decision = await reason_about_event(
    sensor_payload=reading,
    image_url="https://res.cloudinary.com/.../cropped_alert.jpg",
    user_history=history_context,
    behavioral_schema=schema,
    time_of_day="3:17am weekday"
)
# {"confirmed_event_type": "STOVE_LEFT_ON", "severity": "HIGH", "recommended_action": "..."}
```

---

## Fetch.ai — 12 agents, one bureau

HomePulse uses **12 uAgents** registered on Agentverse, all running in a single `Bureau`. Agents communicate by sending typed `Model` messages to each other's addresses.

```
agents/
  sensor_agent.py       — serial reader + anomaly scorer
  triage_agent.py       — Claude: investigate?
  history_agent.py      — MongoDB context fetcher
  vision_agent.py       — OpenCV + Claude vision + Cloudinary
  monitor_agent.py      — Claude: reason + decide
  escalation_agent.py   — severity ladder rules
  notification_agent.py — Claude email + Gmail SMTP
  voice_agent.py        — ElevenLabs TTS + spatial guidance loop
  voice_input_agent.py  — ElevenLabs STT + wake word
  dashboard_agent.py    — Agentverse Chat Protocol / ASI:One
  learning_agent.py     — scheduled: refresh baselines
  report_agent.py       — scheduled: weekly digest
  heartbeat_agent.py    — watchdog: sensor silence alarm
```

The `dashboard_agent` is registered with Agentverse's Chat Protocol so it can receive messages from the ASI:One chat interface — letting caregivers query the system by typing natural language.

---

## ElevenLabs — voice in both directions

**Output (TTS):** When `vision_agent` detects a hazard and can localize it (fractional coordinates from Claude's bounding box), `voice_agent` speaks instructions using ElevenLabs. It runs a correction loop — every ~3 seconds it captures a new frame, calls Claude vision to re-locate the hazard, and speaks updated directional guidance until the user reaches it.

```
"Stove alert. Walk toward the kitchen."
  → [capture new frame → Claude vision → still in upper-left]
"The stove is to your left."
  → [capture new frame → Claude vision → centered, close]
"You're almost there — straight ahead."
```

**Input (STT):** `voice_input_agent` uses ElevenLabs Scribe to listen for a wake word. On activation, it transcribes the user's spoken query, routes it to `dashboard_agent`, and the response comes back via WebSocket to the frontend and/or spoken aloud.

---

## Cloudinary — vision delivery

Every alert frame is uploaded once to `homepulse/raw/{event_id}`. From that single stored image, the app builds two delivery URLs on the fly using Cloudinary's transformation chain:

```
Full crop URL:
  c_crop + fl_relative (from Claude's 0-1 bounding box)
  → e_sharpen:80 → e_improve → q_auto → f_auto → dpr_auto

Thumbnail URL:
  same crop → c_limit (480px wide) → improve → q_auto → f_auto → dpr_auto
```

If a user marks an event as a false positive and `CLOUDINARY_DESTROY_ON_FALSE_POSITIVE=true`, the raw asset is deleted with `invalidate=True` to purge CDN edge caches.

---

## MongoDB — memory and learning

MongoDB stores everything that makes the system smarter over time:

| Collection | What it holds |
|---|---|
| `users` | Name, emergency contacts, preferences |
| `events` | Full event record: sensor payload, image URLs, severity, Claude's reasoning, confirmed status |
| `baselines` | Per-user, per-hour sensor baselines (rolling window) |
| `behavioral_schema` | Learned patterns: typical dinner hour, usual wake time, expected motion levels |
| `sensor_simulation_queue` | Dev tool: API injects readings here; sensor_agent drains it |
| `incidents` | Grouped clusters of related events (same type, close in time) |

`learning_agent` runs every 24 hours and after any confirmed event. It updates thresholds — if SOUND_ANOMALY has a high false positive rate, it raises the trigger threshold. If the user is confirming alerts consistently, it tightens it.

---

## Use cases

| Scenario | How HomePulse handles it |
|---|---|
| **Stove left on at 3 AM** | Sound + heat anomaly → triage flags it → vision sees the stove → Claude confirms HIGH severity → caregiver email with Cloudinary image |
| **Fall suspected** | Sudden acceleration + silence → triage → vision checks if person is on floor → CRITICAL if confirmed → 911 suggestion in email |
| **Faucet running for an hour** | Magnetic/pressure anomaly → triage checks time of day → monitor confirms MEDIUM → user email with cancel window |
| **Caregiver query** | Types "how has Mom been this week?" into ASI:One → dashboard_agent queries MongoDB → responds with summary |
| **Weekly family update** | report_agent fires every 7 days → Claude reads the week's events → writes a plain-English digest to all caregivers |
| **Sensor goes offline** | heartbeat_agent detects silence > 2 min → fires system alert to emergency contacts immediately |

---

## Running locally

### Prerequisites

- Python 3.11+
- Node 20+
- MongoDB Atlas (free tier works) or local MongoDB
- Arduino with LSM9DS1 sensor (optional — use simulation mode without it)
- Webcam (optional — vision agent skips gracefully without it)

### 1. Clone and install

```bash
git clone https://github.com/your-org/buildingtowardssantamonica
cd buildingtowardssantamonica
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in:

```bash
# Required
MONGODB_URI=mongodb+srv://...
MONGODB_DB_NAME=homepulse
ANTHROPIC_API_KEY=sk-ant-...
DEFAULT_USER_ID=<24-char hex ObjectId from seed step below>

# Alerts (optional but recommended)
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx

# Voice (optional)
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM

# Vision (optional)
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
WEBCAM_INDEX=0

# Fetch.ai
FETCHAI_AGENT_SEED=any_random_seed_phrase
AGENTVERSE_KEY=...  # only needed for Agentverse registration

# Hardware (skip to use simulation)
ARDUINO_SERIAL_ENABLED=false
ARDUINO_SERIAL_PORT=COM3
```

### 3. Seed demo data

```bash
python scripts/seed_demo.py
# Prints the DEFAULT_USER_ID — paste it into .env
```

### 4. Register agents (get addresses)

```bash
python scripts/register_agents.py
# Paste printed addresses into agents/agent_messages.py
```

### 5. Start everything

**Terminal 1 — API:**
```bash
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — Agents:**
```bash
python run_agents.py
```

**Terminal 3 — Frontend:**
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173/#dev  (dev console)
# Open http://localhost:5173       (caregiver dashboard)
```

### 6. Trigger a demo event

In the dev console click **"Loud noise (full pipeline)"** — this calls `POST /sensor/simulate` with `force_triage: true`, bypassing baseline math and sending a synthetic event through the entire agent chain. Watch the terminal logs and the live event feed.

Or via curl:
```bash
curl -X POST http://localhost:8000/sensor/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "<DEFAULT_USER_ID>",
    "sound": 850,
    "light": 120,
    "accel_x": 0.1, "accel_y": 0.0, "accel_z": 9.8,
    "magnetic_x": 45.0, "magnetic_y": 12.0, "magnetic_z": -28.0,
    "force_triage": true
  }'
```

---

## Project structure

```
buildingtowardssantamonica/
├── app/
│   ├── main.py                   # FastAPI entry point
│   ├── config.py                 # All env vars (Pydantic Settings)
│   ├── database.py               # Motor async MongoDB client
│   ├── routers/                  # sensor, events, users, zones, alerts,
│   │                             # voice_ws, dashboard, search, incidents
│   ├── services/
│   │   ├── claude_service.py     # All Anthropic API calls (centralized)
│   │   ├── anomaly_detector.py   # Math scoring vs baseline
│   │   ├── cloudinary_service.py # Upload + crop URL builder
│   │   ├── gmail_service.py      # SMTP alert delivery
│   │   ├── tts_service.py        # ElevenLabs TTS
│   │   ├── stt_service.py        # ElevenLabs Scribe STT
│   │   ├── spatial_service.py    # Bounding boxes → voice directions
│   │   ├── learning_service.py   # Threshold + baseline updates
│   │   └── ...
│   └── utils/
│       ├── serial_reader.py      # Background Arduino reader thread
│       └── ...
├── agents/
│   ├── agent_messages.py         # Shared message types + agent addresses
│   ├── sensor_agent.py
│   ├── triage_agent.py
│   ├── history_agent.py
│   ├── vision_agent.py
│   ├── monitor_agent.py
│   ├── escalation_agent.py
│   ├── notification_agent.py
│   ├── voice_agent.py
│   ├── voice_input_agent.py
│   ├── dashboard_agent.py
│   ├── learning_agent.py
│   ├── report_agent.py
│   └── heartbeat_agent.py
├── frontend/
│   └── src/
│       ├── DevConsole.tsx        # Full dev sandbox UI
│       └── pages/HomePulseDashboard.tsx
├── scripts/
│   ├── seed_demo.py              # Create demo user + baselines
│   ├── register_agents.py        # Print Agentverse agent addresses
│   └── calibrate.py             # Manual sensor calibration
├── inputs.ino                    # Arduino sketch (LSM9DS1 + PDM)
├── run_agents.py                 # Bureau entry point (all 12 agents)
├── requirements.txt
└── .env.example
```

---

## API reference (key endpoints)

| Method | Path | Description |
|---|---|---|
| `POST` | `/sensor/reading` | Submit live Arduino reading (synchronous anomaly check) |
| `POST` | `/sensor/simulate` | Inject a test reading into the agent simulation queue |
| `GET` | `/events/{user_id}` | List events for a user (includes image URLs) |
| `PATCH` | `/events/{event_id}/confirm` | Confirm or cancel an event (closes cancel window) |
| `GET` | `/search` | Full-text event search |
| `GET` | `/incidents` | Grouped event clusters by type + time window |
| `GET` | `/alerts` | Alert history + cancel window status |
| `WS` | `/voice/ws` | Bidirectional: receive live alerts, send voice commands |
| `GET` | `/integration/dev-context` | Dev mode bootstrap (returns DEFAULT_USER_ID + config) |

Full curl examples are in `FLOW_AND_TESTING.md`.

---

## Testing

```bash
pytest
```

Tests cover anomaly detection math, baseline computation, Cloudinary URL building, and triage agent behavior. Integration tests assume a running MongoDB instance.

---

## Hackathon tracks

| Track | What we built |
|---|---|
| **Anthropic** | Claude as the reasoning layer at triage, vision, monitor, notification, and digest — all centralized, structured-output calls |
| **Fetch.ai** | 12 uAgents on Agentverse with Chat Protocol; ASI:One compatible dashboard inbox |
| **ElevenLabs** | TTS voice alerts with spatial correction loop; Scribe STT wake word and voice cancel |
| **MongoDB** | Behavioral learning, event history, simulation queue, baseline storage — all async via Motor |
| **Cloudinary** | Single-upload, multi-URL delivery with `fl_relative` crops from Claude bounding boxes; false positive cleanup with CDN invalidation |

Detailed notes for each track are in `pitch/`.

---

## Constraints and honest limitations

- **Hardware demo** requires an Arduino with LSM9DS1 wired and a webcam — simulation mode works without either.
- **Email** requires a Gmail account with 2FA and an app password (no OAuth).
- **Atlas Free Tier** has limited full-text search — falls back to regex if FTS index is not configured.
- **Agentverse external chat** needs `ngrok` or a public tunnel for the webhook + `AGENTVERSE_KEY`.
- Built in 24 hours — production deployment, auth, and multi-user support are not hardened.

---

## License

Hackathon codebase — no formal license. Contact the team before building on it commercially.
