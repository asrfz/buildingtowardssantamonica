# HomePulse AI — Full Project Context

## What This Is
HomePulse AI is a smart home safety and monitoring system built for elderly people and anyone in need of household assistance. It detects invisible household risks (heat anomalies, water leaks, appliances left on, fridge left open) using physical Arduino sensors, then uses computer vision + Cloudinary to visually pinpoint the exact issue, and notifies the user or contacts relevant services via Gmail — all orchestrated by a multi-agent AI system built with FetchAI's uAgents framework + Agentverse.

The system self-learns from past events, building a behavioral schema per user in MongoDB so that over time it becomes more accurate, personalized, and proactive. All agents are registered on Agentverse and implement the Chat Protocol as required by the FetchAI hackathon track.

---

## Target User
- Elderly individuals living alone or with limited mobility
- Anyone who needs passive household monitoring without active effort
- Caregivers who want remote visibility into a household

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python) |
| Agent Framework | FetchAI uAgents + Agentverse (orchestration + scheduling — no built-in LLM) |
| LLM / Reasoning | Anthropic Claude API (`claude-sonnet-4-20250514`) |
| Database | MongoDB (via Motor async driver) |
| Vision | OpenCV + webcam (demo via laptop webcam, index 0) |
| Image Processing | Cloudinary Python SDK (`pip install cloudinary`) |
| Spoken guidance | ElevenLabs TTS (`elevenlabs` + local playback via `pygame`) |
| Email Notifications | Gmail SMTP with App Password (no OAuth needed for demo) |
| Hardware | Arduino (serial communication to Python via pyserial) |
| Frontend (optional) | React via `create-cloudinary-react` scaffold (separate project) |

### LLM Architecture — Critical Rule
FetchAI uAgents is **orchestration only**. It handles agent-to-agent messaging, scheduling, and Agentverse registration — zero built-in intelligence. Claude API (`ANTHROPIC_API_KEY`) is the reasoning brain, injected at specific agent touchpoints only.

**Claude is not invoked on every sensor reading** (that stays local math). A confirmed event uses Claude in layers (triage → optional vision object detection → monitor → email, plus optional per-tick calls during `voice_agent` guidance). Costs stay controlled because raw sensor traffic never hits the API.

| Agent | Calls Claude? | Purpose |
|---|---|---|
| `sensor_agent` | ❌ | Math only — deviation scoring |
| `triage_agent` | ✅ | Is this worth investigating? Noise filter |
| `history_agent` | ❌ | MongoDB reader — pulls user context |
| `vision_agent` | ✅ (vision) | OpenCV frame + Claude object boxes + Cloudinary (`q_auto`); may send `VoiceAlert` |
| `monitor_agent` | ✅ | Text reasoning with cropped image URL + history + sensors |
| `escalation_agent` | ❌ | Rule-based severity ladder |
| `notification_agent` | ✅ | Writes natural language email body |
| `voice_agent` | ✅ (vision) | ElevenLabs TTS + OpenCV ticks + `locate_object_and_user_in_frame` + `spatial_service` |
| `learning_agent` | ✅ optional | Summarizes behavioral pattern changes |
| `report_agent` | ✅ | Weekly digest email written by Claude |
| `heartbeat_agent` | ❌ | Watchdog — no reasoning needed |

---

## Arduino Sensors & What They Detect

The Arduino sends sensor readings over USB serial to the FastAPI backend every 5 seconds.

| Sensor | Arduino Pin Type | What It Detects |
|---|---|---|
| Sound / Microphone | Analog | Water dripping, faucet running, appliance hum, smoke alarm |
| Temperature (DHT22) | Digital | Stove left on, iron left on, fridge open, fire risk |
| Hall Effect (Magnetic) | Digital | Fridge door open/closed, cabinet left open |
| Accelerometer (MPU6050) | I2C | Appliance vibration, off-balance washer, fall detection |
| Pressure sensor | Analog | Secondary confirmation (optional, weakest signal) |

### Serial Payload Format (Arduino → Python)
```json
{
  "sound_level": 412,
  "temperature_c": 34.2,
  "magnetic_state": 1,
  "accel_x": 0.12,
  "accel_y": 0.03,
  "accel_z": 9.81,
  "pressure": 1013,
  "timestamp": "2025-04-25T14:32:00Z"
}
```

---

## Irregularity Detection Logic

### How Baseline is Established
On first run (or manual calibration), the system passively collects sensor readings for a calibration window (default: 48 hours). Stored in MongoDB, used to compute `mean` and `std_dev` per sensor per hour-of-day + day-type.

For demo: baselines are hardcoded via `scripts/seed_demo.py`.

### What Counts as an Irregularity
Any reading exceeding `baseline_mean ± (threshold_multiplier × std_dev)`.
Default `threshold_multiplier = 2.5` — configurable per user per event type.

Time-of-day context is critical:
- Temperature spike at 6pm (dinner) → likely normal
- Same spike at 3am → irregularity

### Core Irregularity Types

| Event Name | Sensors Used | Pattern |
|---|---|---|
| `STOVE_LEFT_ON` | Temperature | Sustained temp rise > 20°C above baseline for 30+ min, no movement |
| `FRIDGE_OPEN` | Magnetic + Temperature | Door open > 3 min + ambient temp rising |
| `FAUCET_RUNNING` | Sound | Continuous water sound > 10 min |
| `WATER_DRIPPING` | Sound | Rhythmic low-volume repeating sound |
| `IRON_LEFT_ON` | Temperature + Accelerometer | Heat spike + zero vibration/movement for 15+ min |
| `APPLIANCE_FAULT` | Accelerometer | Abnormal vibration signature |
| `FIRE_RISK` | Temperature + Sound | Rapid temp spike + loud sound (smoke alarm freq) |
| `FALL_DETECTED` | Accelerometer | Sudden high-G impact + no recovery movement |

---

## Multi-Agent Architecture (FetchAI uAgents + Agentverse)

### Full Agent Flow
```
Arduino Serial
      ↓
sensor_agent              ← hardware bridge, pure math, no LLM
      ↓
triage_agent              ← Claude: is this real? filter noise early
      ↓ [confirmed worth investigating]
      ├── history_agent   ← parallel: pulls MongoDB user context (no LLM)
      └── vision_agent    ← parallel: OpenCV + Claude object boxes + Cloudinary; may → voice_agent
            ↓ [history + vision results to monitor_agent; voice may run in parallel after VoiceAlert]
      monitor_agent       ← Claude: reasoning with image URL + history + sensors
            ↓
      escalation_agent    ← rule-based severity ladder + contact routing (no LLM)
            ↓
      notification_agent  ← Claude: writes email → Gmail SMTP → sent
            ↓
      [60s cancel window]
            ↓
      learning_agent      ← runs every 24h: updates baselines + behavioral schema
      report_agent        ← runs weekly: Claude writes digest → Gmail to caregiver
      heartbeat_agent     ← always running: watchdog for Arduino silence
```

### Agent Responsibilities

#### `sensor_agent`
- Polls Arduino serial every 5 seconds
- Runs `anomaly_detector.score_reading()` — pure math vs baseline
- If threshold crossed → sends `IrregularityEvent` to `triage_agent`
- Registered on Agentverse with Chat Protocol

#### `triage_agent`
- First Claude touchpoint
- Receives raw `IrregularityEvent`
- Sends Claude: sensor readings, deviation score, time of day, user's recent false positive rate
- Claude decides: investigate further or dismiss
- If dismissed → logs to MongoDB as dismissed, chain stops
- If confirmed → fires `history_agent` and `vision_agent` in parallel
- Prevents alert fatigue — critical for elderly users

#### `history_agent`
- No LLM — pure MongoDB reader
- Pulls: last 10 events of this type, overall false positive rate, behavioral schema, time-of-day patterns
- Packages into `UserHistoryContext` and returns to `monitor_agent`

#### `vision_agent`
- Captures a webcam frame via `cv2.VideoCapture` (`WEBCAM_INDEX` in settings)
- Primary: `claude_service.detect_objects_in_frame` on a JPEG of the frame to get fractional boxes for the event’s target object; fallback: MongoDB `room_zones` (pixel boxes; no `VoiceAlert` in that case)
- Uploads the raw frame to Cloudinary, builds a zone crop with `fl_relative` when coords are 0–1, plus sharpen/improve/`q_auto`/`f_auto`, and optionally a second delivery URL with Generative Fill on the full frame (`context_expanded_url` → Mongo `context_expanded_image_url`)
- Returns `VisionResult` (raw + cropped URLs) to `monitor_agent`
- If the zone is fractional, sends `VoiceAlert` to `voice_agent` so TTS and the correction loop can use the same coordinate space as Cloudinary

#### `voice_agent`
- Receives `VoiceAlert` from `vision_agent` when fractional coords exist; speaks via ElevenLabs (`tts_service`) using a warm model for the first line and a low-latency model for corrections
- On an interval, captures another OpenCV frame, encodes to base64 in `cloudinary_service.frame_to_base64`, and calls `locate_object_and_user_in_frame` (no Cloudinary on ticks)
- `spatial_service` turns boxes into short phrases; ends when the object is off-frame, positions converge, or a timeout

#### `monitor_agent`
- Waits for both `history_agent` and `vision_agent` results
- Second (main) Claude touchpoint
- Sends Claude: sensor data, deviation score, cropped image URL, user history, behavioral schema, time of day
- Claude outputs: confirmed event type, severity, recommended action, email draft summary
- Writes full event document to MongoDB `events` collection
- Forwards to `escalation_agent`

#### `escalation_agent`
- No LLM — pure rule engine
- Applies severity ladder:
  - LOW → log only, stop
  - MEDIUM → notify user only
  - HIGH → notify user + emergency contact
  - CRITICAL → notify all + suggest relevant service (plumber, fire dept, etc.)
- Starts 60-second cancel window for non-CRITICAL
- Forwards full context to `notification_agent`

#### `notification_agent`
- Third Claude touchpoint
- Claude writes warm, plain-language email body (suitable for elderly users — no jargon)
- Sends via `gmail_service.send_alert()` using Gmail SMTP
- Sends to emergency contacts if escalation_agent flagged HIGH/CRITICAL
- Handles cancel window: user cancels within 60s → marks event as false positive in MongoDB

#### `learning_agent`
- Scheduled: every 24 hours + triggered after any confirmed event
- Calls `learning_service.refresh_behavioral_schema()`
- Updates per-hour baselines with new confirmed data
- Adjusts per-event-type `threshold_multiplier` based on false positive rate
- Optional Claude call to summarize what changed in the user's pattern

#### `report_agent`
- Scheduled: every 7 days
- Pulls last 7 days of events from MongoDB
- Claude writes a readable weekly digest covering: what happened, patterns, recommendations
- Example: "This week, the stove was left on twice — both after 8pm on weekdays. A dinner reminder could help."
- Sends to user + all caregivers via Gmail SMTP

#### `heartbeat_agent`
- Runs every 60 seconds
- Checks: has `sensor_agent` reported in the last 2 minutes?
- If Arduino goes silent (power loss, disconnect, crash) → fires "system offline" alert immediately
- No LLM — pure timestamp comparison
- Critical for elderly users: a dead sensor is as dangerous as a real event

### Agentverse Registration (Hackathon Requirement)
All agents must be registered on Agentverse and implement Chat Protocol:

```python
from uagents.protocols.chat import ChatProtocol, ChatMessage

agent.include(ChatProtocol())

@agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatMessage(content=f"HomePulse {agent.name} online"))
```

This makes agents discoverable and interactive via ASI:One, satisfying the mandatory FetchAI hackathon requirement.

---

## Cloudinary Usage

Cloudinary is used as a **reporting tool**, not just storage.

### Installation
```bash
pip install cloudinary
```
Do NOT use `create-cloudinary-react` in the backend — that is a React frontend scaffolding tool only.

### Configuration
```python
import cloudinary
cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET
)
```
Call once at startup in `app/main.py`.

### What Happens Per Event
1. Raw webcam frame uploaded via `cloudinary.uploader.upload()`
2. Zone bounding box (Claude fractions with `fl_relative`, or Mongo pixel coords) passed as crop parameters
3. **Evidence crop URL:** crop → sharpen → improve → `q_auto` → `f_auto`
4. **Optional context URL (same upload):** pad + Generative Fill (`b_gen_fill`) on the full frame for AI-extended borders — **illustrative only**; toggled via `CLOUDINARY_AI_CONTEXT_EXPAND`
5. Public URLs stored on the event (`cropped_image_url`, `raw_image_url`, `context_expanded_image_url`) and used in the dev UI / WebSocket alert payload; emails still prioritize the zone crop for diagnosis

### Transformation Example
```
https://res.cloudinary.com/{cloud}/image/upload/
  c_crop,x_100,y_200,w_300,h_200/
  e_sharpen:80/
  e_improve/
  homepulse/{event_id}.jpg
```

### Room Zone Mapping (stored in MongoDB `room_zones`)
```json
{
  "zones": {
    "sink":   {"x": 100, "y": 200, "w": 300, "h": 200},
    "stove":  {"x": 400, "y": 150, "w": 280, "h": 220},
    "fridge": {"x": 50,  "y": 100, "w": 200, "h": 350}
  }
}
```

---

## Gmail Integration

### Method: Gmail SMTP + App Password
- No OAuth, no API console setup
- Requires 2FA on Gmail account → generate 16-character App Password
- Works in 10 lines of Python via `smtplib`

### Alert Email
- Subject: `[HomePulse HIGH] Stove anomaly detected — 3:12 AM`
- Body written by Claude via `notification_agent` — warm, plain language, no jargon
- Contains: event description, sensor readings vs baseline, Cloudinary cropped image, severity, recommended action, cancel option

### Escalation
| Severity | Recipients | Cancel Window |
|---|---|---|
| LOW | Log only | N/A |
| MEDIUM | User email | 60 seconds |
| HIGH | User + emergency contact | 60 seconds |
| CRITICAL | User + emergency contact + service suggestion | No cancel |

### Weekly Report Email
Sent by `report_agent` every 7 days to user + caregivers. Written by Claude. Covers patterns, trends, and plain-language recommendations.

---

## Self-Learning System

### What Gets Learned
- Per-user sensor baselines per hour + day-type
- False positive rate per event type
- Time-of-day activity patterns
- User response behavior (cancel rate per event type)

### How It Updates
- `confirmed: true` → tighten threshold slightly for this event type
- `confirmed: false` (cancelled) → loosen threshold, log as false positive
- `threshold_multiplier` stored per event type in `behavioral_schema` collection

---

## Environment Variables Required
```
MONGODB_URI=mongodb+srv://...
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
GMAIL_ADDRESS=...
GMAIL_APP_PASSWORD=...        # 16-char App Password (requires 2FA on account)
ARDUINO_SERIAL_PORT=/dev/ttyUSB0   # or COM3 on Windows
ARDUINO_BAUD_RATE=9600
FETCHAI_AGENT_SEED=...
ANTHROPIC_API_KEY=...         # Claude API — triage, monitor, notification, report agents
```

---

## Demo Scope (Hackathon)
Three live scenarios:
1. **Stove/heat left on** — temp spike → triage → vision crops stove zone → Gmail alert
2. **Faucet running** — sound anomaly → triage → vision crops sink zone → Gmail alert
3. **Fridge left open** — magnetic + temp → triage → vision crops fridge zone → Gmail alert

All 10 agents running. Baselines hardcoded for speed. MongoDB updates live to show self-learning. All agents registered on Agentverse with Chat Protocol.
