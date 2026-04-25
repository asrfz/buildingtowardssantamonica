# HomePulse AI — Full Agent Chain Complete

## Status: COMPLETE ✅
**Built:** 2026-04-25

---

## What Changed from Milestone 1

Milestone 1 had a shortcut in `triage_agent.py`: after Claude said "investigate", it skipped directly to `notification_agent`. That is now replaced with the full chain.

### Updated: `agents/triage_agent.py`
- Removed direct `EscalationOrder` send to `notification_agent`
- Now sends `TriageResult` to **both `history_agent` AND `vision_agent` in parallel**
- `monitor_agent` collects both results before calling Claude

### Full Pipeline (all 10 agents active)

```
Arduino Serial
      ↓
sensor_agent       (every 5s — math only, no LLM)
      ↓
triage_agent       (Claude call #1 — noise filter)
      ↓ [investigate=True]
      ├── history_agent  ← parallel: MongoDB context
      └── vision_agent   ← parallel: webcam → Cloudinary
            ↓ [both arrive at monitor_agent]
      monitor_agent      (Claude call #2 — full reasoning with image + history)
            ↓
      escalation_agent   (rule engine — severity ladder, contact routing)
            ↓
      notification_agent (Claude call #3 — writes email body → Gmail SMTP)
            ↓
      [60s cancel window — user can cancel via PATCH /alerts/{id}/cancel]

Scheduled:
      learning_agent     (every 24h — refreshes baselines + behavioral schema)
      report_agent       (every 7d — Claude digest email)
      heartbeat_agent    (every 60s — fires offline alert if sensor goes silent)
```

---

## New Files Added

### Services
| File | Purpose |
|------|---------|
| `app/services/cloudinary_service.py` | Upload frame, crop zone, return public URLs |
| `app/services/vision_service.py` | Webcam capture (OpenCV) + zone lookup by event type |
| `app/services/baseline_service.py` | Welford online stats update for sensor baselines |
| `app/services/learning_service.py` | Record outcomes, adjust thresholds, refresh schema |

### Models
| File | Purpose |
|------|---------|
| `app/models/user.py` | `UserCreate`, `UserResponse`, `UserUpdate`, `EmergencyContact` |
| `app/models/zone.py` | `ZoneMap`, `ZoneBounds`, `ZoneMapResponse`, `ZoneMapUpdate` |
| `app/models/alert.py` | `AlertLog`, `AlertCancelResponse` |
| `app/models/behavioral_schema.py` | `BehavioralSchemaResponse`, `EventTypeStats` |

### Schemas
| File | Purpose |
|------|---------|
| `app/schemas/user_schema.py` | `build_user_doc()` |
| `app/schemas/zone_schema.py` | `build_zone_doc()` |
| `app/schemas/alert_schema.py` | `build_alert_doc()` |
| `app/schemas/behavioral_schema.py` | `build_behavioral_schema_doc()` |

### Routers
| File | Endpoints |
|------|-----------|
| `app/routers/events.py` | `GET /events/{user_id}`, `GET /events/detail/{id}`, `PATCH /events/{id}/confirm` |
| `app/routers/users.py` | `POST /users`, `GET /users/{id}`, `PATCH /users/{id}` |
| `app/routers/zones.py` | `GET /zones/{user_id}`, `POST /zones/{user_id}` |
| `app/routers/alerts.py` | `GET /alerts/{user_id}`, `PATCH /alerts/{id}/cancel` |

### Agents
| File | Role |
|------|------|
| `agents/history_agent.py` | Pulls last 10 events + behavioral schema → sends `UserHistoryContext` to monitor |
| `agents/vision_agent.py` | Webcam → OpenCV → Cloudinary → sends `VisionResult` to monitor (empty URLs if webcam unavailable) |
| `agents/monitor_agent.py` | Waits for both history + vision, calls Claude reasoning, updates MongoDB, sends `MonitorDecision` to escalation |
| `agents/escalation_agent.py` | Severity ladder → selects recipients + cancel window → sends `EscalationOrder` to notification |
| `agents/learning_agent.py` | 24h schedule: `refresh_behavioral_schema()` + `adjust_threshold()` per event type |
| `agents/report_agent.py` | 7d schedule: Claude weekly digest → Gmail to user + caregivers |
| `agents/heartbeat_agent.py` | 60s poll: fires offline alert if sensor_agent silent > `HEARTBEAT_TIMEOUT_SECONDS` |

### Scripts
| File | Purpose |
|------|---------|
| `scripts/calibrate.py` | Live baseline calibration from real Arduino over configurable window |
| `scripts/test_serial.py` | Print raw serial JSON from Arduino for debugging |

### Hardware
| File | Purpose |
|------|---------|
| `arduino/homepulse_sensor/homepulse_sensor.ino` | Arduino sketch — reads DHT22, MPU6050, sound, magnetic, pressure → JSON every 5s |

---

## How to Run All 10 Agents

### Start FastAPI
```bash
uvicorn app.main:app --reload
```

### Start all agents (10 terminals or use a process manager)
```bash
python agents/sensor_agent.py
python agents/triage_agent.py
python agents/history_agent.py
python agents/vision_agent.py
python agents/monitor_agent.py
python agents/escalation_agent.py
python agents/notification_agent.py
python agents/learning_agent.py
python agents/report_agent.py
python agents/heartbeat_agent.py
```

### Trigger a demo event
```bash
python scripts/simulate_trigger.py stove    # temp spike → STOVE_LEFT_ON
python scripts/simulate_trigger.py faucet   # sound → FAUCET_RUNNING
python scripts/simulate_trigger.py fridge   # magnetic → FRIDGE_OPEN
```

---

## Full Data Flow (Step by Step)

1. **sensor_agent** reads from serial queue (or simulated via `/sensor/simulate`)
2. Calls `anomaly_detector.score_reading()` — pure math vs baselines
3. If triggered, sends `IrregularityEvent` to **triage_agent**
4. **triage_agent** calls Claude: `triage_event()` — is this worth investigating?
5. Writes event to MongoDB (status: `dismissed` or `triaged`)
6. If `investigate=True`, sends `TriageResult` to **history_agent** AND **vision_agent** simultaneously
7. **history_agent** queries last 10 events + behavioral schema → sends `UserHistoryContext` to **monitor_agent**
8. **vision_agent** captures webcam frame → looks up zone → uploads to Cloudinary → sends `VisionResult` to **monitor_agent**
9. **monitor_agent** collects both; once both arrive calls Claude: `reason_about_event()` with image + history
10. Updates event in MongoDB with confirmed type, severity, image URLs, reasoning
11. Sends `MonitorDecision` to **escalation_agent**
12. **escalation_agent** applies severity ladder: LOW → log only; MEDIUM → user only; HIGH/CRITICAL → user + emergency contacts
13. Sets cancel window (0 for CRITICAL)
14. Sends `EscalationOrder` to **notification_agent**
15. **notification_agent** calls Claude: `write_alert_email()` — warm HTML email body
16. Sends via Gmail SMTP, updates event status in MongoDB (`notified`)
17. User can cancel within cancel window via `PATCH /alerts/{id}/cancel` → triggers `record_outcome(confirmed=False)`
18. **learning_agent** (24h): recomputes all false positive rates, adjusts thresholds
19. **report_agent** (7d): Claude digest email to user + caregivers
20. **heartbeat_agent** (60s): fires offline alert if sensor_agent hasn't checked in

---

## Vision Agent Graceful Fallback

`vision_agent` sends an empty `VisionResult` (empty URL strings) if:
- Webcam is unavailable (`cv2.VideoCapture(0)` fails)
- No zone mapping exists for the event type
- Cloudinary upload fails

`monitor_agent` handles empty `image_url` gracefully — Claude still reasons with sensor + history alone.

---

## Cancel Window Flow

1. `escalation_agent` sets `cancel_window_seconds = CANCEL_WINDOW_SECONDS` (default 60) for non-CRITICAL
2. `notification_agent` includes cancel instructions in the email (Claude writes them in)
3. User hits `PATCH /alerts/{alert_id}/cancel`
4. `alerts.py` router calls `learning_service.record_outcome(confirmed=False)`
5. Event is marked as `false_positive` in MongoDB
6. `learning_agent` on its next cycle adjusts the threshold for that event type

---

## Key Agent Addresses to Fill In

After running `python scripts/register_agents.py`, fill all 10 constants in `agents/agent_messages.py`:

```python
SENSOR_AGENT_ADDRESS
TRIAGE_AGENT_ADDRESS
HISTORY_AGENT_ADDRESS
VISION_AGENT_ADDRESS
MONITOR_AGENT_ADDRESS
ESCALATION_AGENT_ADDRESS
NOTIFICATION_AGENT_ADDRESS
LEARNING_AGENT_ADDRESS
REPORT_AGENT_ADDRESS
HEARTBEAT_AGENT_ADDRESS
```

---

## What Remains (Future Work)

- Arduino `timestamp` field: currently the sketch doesn't send a timestamp (Python uses `datetime.utcnow()` as a fallback). Add NTP or RTC module to Arduino for accurate hardware timestamps.
- Multi-user support: `DEFAULT_USER_ID` is a single-user shortcut. Full multi-user needs user resolution from the sensor reading itself (device registration).
- Agentverse registration: submit all 10 agents to the FetchAI Agentverse dashboard for the hackathon track requirement.
- Cancel window timer: currently the user cancels manually via API. Could add a uAgents `on_interval` in `notification_agent` to auto-confirm after the window expires.
- Tests: `tests/` directory exists — write test files per the structure spec.
