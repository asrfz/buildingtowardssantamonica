# HomePulse AI — Project Structure

## Root Layout

```
homepulse/
│
├── CONTEXT.md                  ← Full project context (read first)
├── SCHEMA.md                   ← MongoDB schema definitions
├── STRUCTURE.md                ← This file
├── AGENT_CONTEXT.md            ← Coding patterns for AI agents
├── .env                        ← All environment variables (never commit)
├── .env.example                ← Template for .env
├── requirements.txt            ← Python dependencies
├── README.md                   ← Setup instructions
│
├── .claude/
│   └── claude.md               ← Symlink or copy of CONTEXT.md (picked up by Claude Code / Cursor)
│
├── arduino/
│   └── homepulse_sensor/
│       └── homepulse_sensor.ino   ← Arduino sketch (reads sensors, outputs JSON over serial)
│
├── app/                        ← FastAPI application
│   ├── main.py                 ← App entry point, startup events, router includes
│   ├── config.py               ← Pydantic Settings — all env vars loaded here
│   ├── database.py             ← Motor async MongoDB client + collection accessors
│   │
│   ├── models/                 ← Pydantic models (API request/response shapes)
│   │   ├── user.py
│   │   ├── event.py
│   │   ├── sensor.py
│   │   ├── zone.py
│   │   ├── alert.py
│   │   └── behavioral_schema.py
│   │
│   ├── schemas/                ← Raw dicts for MongoDB document construction (Motor)
│   │   ├── user_schema.py
│   │   ├── event_schema.py
│   │   ├── baseline_schema.py
│   │   ├── zone_schema.py
│   │   ├── behavioral_schema.py
│   │   └── alert_schema.py
│   │
│   ├── routers/                ← FastAPI route handlers
│   │   ├── sensor.py           ← POST /sensor/reading
│   │   ├── events.py           ← GET/POST/PATCH /events
│   │   ├── users.py            ← GET/POST/PATCH /users
│   │   ├── zones.py            ← GET/POST /zones
│   │   └── alerts.py           ← GET/PATCH /alerts
│   │
│   ├── services/               ← Business logic (called by routers + agents)
│   │   ├── anomaly_detector.py   ← Compare reading to baseline, compute deviation score
│   │   ├── baseline_service.py   ← Compute + update sensor baselines in MongoDB
│   │   ├── cloudinary_service.py ← Upload frame, apply crop + enhance transformation
│   │   ├── gmail_service.py      ← Gmail SMTP: send alert + weekly digest emails
│   │   ├── vision_service.py     ← Webcam capture (OpenCV) + zone lookup
│   │   ├── learning_service.py   ← Update baselines + behavioral schema post-event
│   │   └── claude_service.py     ← All Anthropic API calls centralized here
│   │
│   └── utils/
│       ├── serial_reader.py    ← Background thread: reads Arduino serial JSON stream
│       ├── time_utils.py       ← hour_of_day(), day_type() helpers
│       └── severity.py         ← deviation_score → severity level mapping
│
├── agents/                     ← FetchAI uAgents (all registered on Agentverse)
│   │
│   ├── agent_messages.py       ← All shared message types (Model subclasses)
│   │
│   ├── sensor_agent.py         ← Polls Arduino serial, scores deviation, fires to triage
│   ├── triage_agent.py         ← Claude: filter noise — is this worth investigating?
│   ├── history_agent.py        ← MongoDB reader: pulls user context for monitor_agent
│   ├── vision_agent.py         ← Webcam → OpenCV → Cloudinary → returns image URLs
│   ├── monitor_agent.py        ← Claude: full reasoning with image + history → decision
│   ├── escalation_agent.py     ← Rule engine: severity ladder + contact routing
│   ├── notification_agent.py   ← Claude: writes email body → Gmail SMTP
│   ├── learning_agent.py       ← Scheduled 24h: updates baselines + behavioral schema
│   ├── report_agent.py         ← Scheduled weekly: Claude digest email to caregiver
│   └── heartbeat_agent.py      ← Watchdog: fires alert if Arduino goes silent
│
├── scripts/
│   ├── seed_demo.py            ← Seed MongoDB: demo user, hardcoded baselines, room zones
│   ├── calibrate.py            ← Manual calibration window runner
│   ├── test_serial.py          ← Test Arduino serial connection
│   └── register_agents.py      ← Print all agent addresses for Agentverse registration
│
└── tests/
    ├── test_anomaly_detector.py
    ├── test_baseline_service.py
    ├── test_cloudinary_service.py
    ├── test_gmail_service.py
    ├── test_triage_agent.py
    └── test_escalation_agent.py
```

---

## Key File Responsibilities

### `app/main.py`
- FastAPI app init
- Startup: connect MongoDB, init Cloudinary config, start serial reader thread
- Include all routers

### `app/config.py`
- Pydantic `Settings` class reading from `.env`
- Single import everywhere: `from app.config import settings`
- Exposes: all DB, Cloudinary, Gmail, Arduino, FetchAI, Anthropic settings

### `app/database.py`
- Motor async client singleton
- `get_db()` FastAPI dependency
- Collections: `users`, `events`, `sensor_baselines`, `room_zones`, `behavioral_schema`, `alert_log`

### `app/services/claude_service.py`
- **All Anthropic API calls live here** — never call Anthropic directly from agents
- `triage_event(sensor_payload, deviation_score, hour, day_type, false_positive_rate) → TriageResult`
- `reason_about_event(sensor_data, history, image_url, time_context) → MonitorDecision`
- `write_alert_email(event, user, image_url) → str` (HTML email body)
- `write_weekly_digest(events_list, user) → str` (HTML digest body)
- Model used: `claude-sonnet-4-20250514`
- Max tokens: 1000 per call (sufficient for all use cases)

### `app/services/gmail_service.py`
- `send_alert(user, event, image_url, email_body) → bool`
- `send_to_contact(contact, event, image_url, email_body) → bool`
- `send_weekly_digest(recipients, digest_html) → bool`
- `send_system_offline_alert(user) → bool`
- All use Gmail SMTP SSL port 465 with App Password

### `app/services/vision_service.py`
- `capture_frame() → np.ndarray` — OpenCV webcam index from settings
- `get_zone_for_event(user_id, event_type, db) → dict | None` — zone bounding box lookup

### `app/services/cloudinary_service.py`
- `upload_and_crop(frame, event_id, zone) → {raw_url, cropped_url}`
- Applies: crop to zone → e_sharpen:80 → e_improve

### `app/services/anomaly_detector.py`
- `score_reading(user_id, payload, db) → AnomalyResult`
- `classify_temp_event(payload) → str`
- `classify_sound_event(payload) → str`
- `compute_severity(deviation_score) → str`

### `app/services/learning_service.py`
- `update_baseline(user_id, payload, hour, day_type, db)`
- `record_outcome(event_id, confirmed, db)`
- `refresh_behavioral_schema(user_id, db)`
- `adjust_threshold(user_id, event_type, false_positive_rate, db)`

### `agents/agent_messages.py`
All inter-agent message types:
```python
class SensorReading(Model): ...
class IrregularityEvent(Model): ...       # sensor_agent → triage_agent
class TriageResult(Model): ...            # triage_agent → history_agent + vision_agent
class UserHistoryContext(Model): ...      # history_agent → monitor_agent
class VisionResult(Model): ...           # vision_agent → monitor_agent
class MonitorDecision(Model): ...        # monitor_agent → escalation_agent
class EscalationOrder(Model): ...        # escalation_agent → notification_agent
class NotificationRequest(Model): ...    # internal use
class HeartbeatStatus(Model): ...        # heartbeat_agent → escalation_agent
```

---

## API Routes

### Sensor
| Method | Path | Description |
|---|---|---|
| POST | `/sensor/reading` | Receive sensor payload from Arduino bridge |
| GET | `/sensor/baseline/{user_id}` | Get current baseline for user |

### Events
| Method | Path | Description |
|---|---|---|
| GET | `/events/{user_id}` | List all events for user |
| GET | `/events/detail/{event_id}` | Get single event detail |
| PATCH | `/events/{event_id}/confirm` | Confirm or cancel event (triggers learning) |

### Users
| Method | Path | Description |
|---|---|---|
| POST | `/users` | Create user |
| GET | `/users/{user_id}` | Get user profile + behavioral schema |
| PATCH | `/users/{user_id}` | Update preferences / threshold |

### Zones
| Method | Path | Description |
|---|---|---|
| GET | `/zones/{user_id}` | Get room zone map |
| POST | `/zones/{user_id}` | Set or update zone map |

### Alerts
| Method | Path | Description |
|---|---|---|
| GET | `/alerts/{user_id}` | List alert history |
| PATCH | `/alerts/{alert_id}/cancel` | Cancel pending alert within cancel window |

---

## Dependencies (`requirements.txt`)

```
fastapi
uvicorn[standard]
motor                   # async MongoDB driver
pydantic
pydantic-settings
python-dotenv
pyserial                # Arduino serial
opencv-python           # webcam + CV
cloudinary              # Cloudinary Python SDK
anthropic               # Claude API — LLM reasoning layer
uagents                 # FetchAI uAgents + Agentverse
numpy
Pillow
```

---

## Environment Variables (`.env.example`)

```bash
# MongoDB
MONGODB_URI=mongodb+srv://username:password@cluster.mongodb.net/homepulse

# Cloudinary
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret

# Gmail (App Password — requires 2FA enabled on account)
GMAIL_ADDRESS=your_gmail@gmail.com
GMAIL_APP_PASSWORD=xxxx_xxxx_xxxx_xxxx

# Arduino
ARDUINO_SERIAL_PORT=/dev/ttyUSB0
# Windows: ARDUINO_SERIAL_PORT=COM3
ARDUINO_BAUD_RATE=9600
WEBCAM_INDEX=0

# FetchAI
FETCHAI_AGENT_SEED=some_random_seed_phrase_here

# Anthropic Claude API
# Model: claude-sonnet-4-20250514
# Called by: triage_agent, monitor_agent, notification_agent, report_agent
ANTHROPIC_API_KEY=sk-ant-...

# App Settings
APP_ENV=development
DEFAULT_USER_ID=replace_with_seeded_user_object_id
CANCEL_WINDOW_SECONDS=60
THRESHOLD_MULTIPLIER=2.5
CALIBRATION_HOURS=48
HEARTBEAT_TIMEOUT_SECONDS=120
REPORT_SCHEDULE_DAYS=7
```

---

## Coding Conventions

- All DB operations use `async/await` with Motor — never PyMongo sync
- All service functions are `async def`
- `ObjectId` from `bson` for MongoDB IDs; serialize to `str` in Pydantic responses
- All timestamps stored as UTC `datetime` — always use `datetime.utcnow()`
- Agent messages extend `uagents.Model`
- All Anthropic API calls go through `app/services/claude_service.py` — never call Anthropic directly from agent files
- Pydantic models in `app/models/` are for API I/O only
- Raw dicts in `app/schemas/` are for MongoDB document construction
- All service functions return `None` on failure and log the error — never raise to agent layer
- Never hardcode user IDs except in `scripts/seed_demo.py`
- Agent addresses go in `agents/agent_messages.py` as constants after first run
