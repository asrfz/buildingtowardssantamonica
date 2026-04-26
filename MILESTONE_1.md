# HomePulse AI — Milestone 1 Progress

## Status: SUPERSEDED by Milestone 2 ✅
**Built:** 2026-04-25 | **Superseded:** 2026-04-25
> See `MILESTONE_2.md` for the full agent chain. The Milestone 1 shortcut in `triage_agent.py` has been replaced with the real history + vision → monitor → escalation flow.

---

## What Was Built

Milestone 1 implements the happy-path MVP:

```
serial_reader → sensor_agent → triage_agent (Claude) → notification_agent (Claude + Gmail)
```

Sensor reads in → anomaly scored → Claude decides if it's real → email sent. No Arduino required for demo (use `scripts/simulate_trigger.py`).

---

## Files Created

### Foundation
| File | Purpose |
|------|---------|
| `requirements.txt` | All Python dependencies |
| `app/config.py` | Pydantic Settings — all env vars in one place |
| `app/database.py` | Motor async MongoDB client singleton |

### Models & Schemas
| File | Purpose |
|------|---------|
| `app/models/sensor.py` | `SensorPayload` — validates Arduino JSON |
| `app/models/event.py` | `IrregularityEvent`, `EventResponse`, `EventDetail` |
| `app/schemas/event_schema.py` | `build_event_doc()` — constructs MongoDB event documents |

### Utilities
| File | Purpose |
|------|---------|
| `app/utils/serial_reader.py` | Background thread reading Arduino serial; `inject_reading()` for demo |
| `app/utils/time_utils.py` | `hour_of_day()`, `day_type()` helpers |
| `app/utils/severity.py` | `compute_severity(score)` → LOW/MEDIUM/HIGH/CRITICAL |

### Services
| File | Purpose |
|------|---------|
| `app/services/anomaly_detector.py` | Pure-math baseline comparison; returns `AnomalyResult` |
| `app/services/claude_service.py` | All Claude API calls (triage, reason, email, digest) |
| `app/services/gmail_service.py` | Gmail SMTP send functions |

### FastAPI
| File | Purpose |
|------|---------|
| `app/main.py` | App entry point, lifespan hooks, router mounts |
| `app/routers/sensor.py` | `POST /sensor/reading`, `POST /sensor/simulate`, `GET /sensor/baseline/{id}` |

### Agent Layer
| File | Purpose |
|------|---------|
| `agents/agent_messages.py` | All uAgents `Model` message types + address constants |
| `agents/sensor_agent.py` | Polls serial queue every 5s, scores readings, fires to triage |
| `agents/triage_agent.py` | Claude noise filter → writes to MongoDB → forwards to notification |
| `agents/notification_agent.py` | Claude writes email body → Gmail SMTP → updates MongoDB |

### Scripts
| File | Purpose |
|------|---------|
| `scripts/seed_demo.py` | Creates demo user, baselines, room zones, behavioral schema |
| `scripts/register_agents.py` | Prints all 10 agent addresses to paste into `agent_messages.py` |
| `scripts/simulate_trigger.py` | Injects stove/faucet/fridge scenario via HTTP without Arduino |

---

## How to Run

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Fill in `.env`
Copy `.env.example` to `.env` and fill in:
- `MONGODB_URI` — MongoDB Atlas free tier works
- `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD` (16-char App Password, requires 2FA)
- `ANTHROPIC_API_KEY`
- `FETCHAI_AGENT_SEED` — any random string, keep it stable
- `ARDUINO_SERIAL_PORT` — `COM3` on Windows (skip if using simulation)

### 3. Seed the database
```bash
python scripts/seed_demo.py
```
Copy the printed ObjectId into `.env` as `DEFAULT_USER_ID=<id>`

### 4. Get agent addresses
```bash
python scripts/register_agents.py
```
Paste the 3 relevant lines into `agents/agent_messages.py`:
```python
SENSOR_AGENT_ADDRESS       = "agent1q..."
TRIAGE_AGENT_ADDRESS       = "agent1q..."
NOTIFICATION_AGENT_ADDRESS = "agent1q..."
```

### 5. Start the FastAPI server
```bash
uvicorn app.main:app --reload
```

### 6. Start agents (3 separate terminals)
```bash
# Terminal 1
python agents/triage_agent.py

# Terminal 2
python agents/notification_agent.py

# Terminal 3 (start last — it polls immediately)
python agents/sensor_agent.py
```

### 7. Trigger a demo event
**With Arduino:** plug in and readings fire automatically.

**Without Arduino (simulation):**
```bash
python scripts/simulate_trigger.py stove    # temp spike
python scripts/simulate_trigger.py faucet   # sound anomaly
python scripts/simulate_trigger.py fridge   # door open
```

### 8. Watch it work
- Agent terminals log the full chain: `Anomaly → Triaging → Triage result → Writing email → Email sent`
- Check your inbox — email arrives within ~30 seconds
- MongoDB `events` collection shows the full event record

---

## Key Design Decisions

**Claude API calls use `asyncio.to_thread()`** — the Anthropic SDK is synchronous; wrapping it prevents blocking the uAgents event loop.

**JSON fence stripping** — Claude occasionally wraps JSON in ` ```json ``` ` fences. `claude_service._parse_json()` strips these before parsing.

**uAgents Model has no `datetime` fields** — uAgents uses Pydantic v1 internally. All timestamps are ISO strings (`timestamp_iso: str`).

**`inject_reading()` in serial_reader** — lets the FastAPI `/sensor/simulate` endpoint push a fake reading into the same queue `sensor_agent` drains, so the demo works without hardware.

**Milestone 1 shortcut in `triage_agent`** — after Claude says "investigate", the triage agent sends directly to `notification_agent` (bypassing history/vision/monitor/escalation). See the `# Milestone 1` comment in `triage_agent.py:72`.

---

## Trigger Thresholds (seeded baselines)

| Sensor | Baseline mean | Std dev | Triggers above |
|--------|--------------|---------|----------------|
| Temperature | 22.0°C | 1.5°C | **25.75°C** (= 22 + 2.5×1.5) |
| Sound | 200 (ADC) | 50 | **325** (= 200 + 2.5×50) |
| Magnetic | 0 (closed) | 0.1 | Door **open** (state=1) |

---

## What Milestone 2 Adds

- `history_agent` — pulls MongoDB user context (no LLM)
- `vision_agent` — webcam → OpenCV → Cloudinary (zone crop + optional Generative Fill context URL) → image URLs
- `monitor_agent` — second Claude call with image + history → full decision
- `escalation_agent` — rule-based severity ladder + contact routing
- `learning_agent` — scheduled 24h baseline updates
- `report_agent` — weekly Claude digest email
- `heartbeat_agent` — watchdog for Arduino silence
- Remove the Milestone 1 shortcut in `triage_agent.py` and wire in the full chain

The `agents/agent_messages.py` already defines all message types for Milestone 2 agents.
