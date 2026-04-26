# HomePulse AI — Agent Coding Context

> Written for AI coding agents working on this codebase.
> Read order: CONTEXT.md → SCHEMA.md → STRUCTURE.md → this file.
> This file tells you HOW to implement each piece.

---

## Golden Rules

1. **Always `async/await`** — Motor is async. Never use PyMongo sync.
2. **Settings from config** — never `os.environ` directly. Always `from app.config import settings`.
3. **ObjectId** — use `bson.ObjectId` for DB queries, serialize to `str` in Pydantic.
4. **UTC everywhere** — always `datetime.utcnow()`, never `datetime.now()`.
5. **Claude calls go through `claude_service.py`** — never import `anthropic` directly in agent files.
6. **Agents don't touch DB directly** — agents call FastAPI services via HTTP or import service functions.
7. **Sensor readings are untrusted** — validate ranges before processing.
8. **Claude is not for raw sensor streaming** — never call Claude on every 5s sensor reading. A confirmed event may use Claude several times: triage, object detection in `vision_service`, monitor reasoning, optional `voice_agent` correction ticks — each is intentional, not a sensor poll.

---

## Full Data Flow (step by step)

```
1.  Arduino sends JSON over serial every 5s
2.  serial_reader.py (background thread) parses → SensorPayload
3.  sensor_agent receives payload
4.  Calls anomaly_detector.score_reading() — pure math
5.  If triggered → sends IrregularityEvent to triage_agent
6.  triage_agent calls Claude (claude_service.triage_event())
7.  Claude returns: investigate=True/False + reasoning
8.  If dismissed → log to MongoDB, stop chain
9.  If confirmed → send TriageResult to history_agent AND vision_agent (parallel)
10. history_agent pulls MongoDB context → sends UserHistoryContext to monitor_agent
11. vision_agent captures frame → OpenCV; Claude vision finds zone (or Mongo `room_zones` fallback) → Cloudinary upload + crop (`q_auto`) → VisionResult to monitor_agent; if zones are fractional (`pct`), VoiceAlert to voice_agent
11a. voice_agent (only if step 11 sent VoiceAlert): initial phrase via ElevenLabs (`tts_service`); then every ~3s OpenCV frame → JPEG base64 → `locate_object_and_user_in_frame` → `spatial_service` → ElevenLabs until timeout/retrieved (Cloudinary not used on ticks)
12. monitor_agent waits for both, then calls Claude (claude_service.reason_about_event())
13. Claude returns: event_type, severity, recommended_action, email_summary
14. monitor_agent writes event to MongoDB events collection
15. monitor_agent sends MonitorDecision to escalation_agent
16. escalation_agent applies severity ladder → sends EscalationOrder to notification_agent
17. notification_agent calls Claude (claude_service.write_alert_email())
18. Claude returns HTML email body
19. notification_agent sends via gmail_service.send_alert()
20. Starts cancel window timer (60s for non-CRITICAL)
21. After cancel window or user response → calls learning_service.record_outcome()
22. learning_agent (scheduled 24h) → refresh_behavioral_schema()
23. report_agent (scheduled 7d) → Claude digest → gmail_service.send_weekly_digest()
24. heartbeat_agent (every 60s) → checks sensor_agent last_seen → fires offline alert if silent
```

---

## Claude Service — All LLM Calls Centralized

```python
# app/services/claude_service.py
import anthropic
from app.config import settings

client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
MODEL = "claude-sonnet-4-20250514"

async def triage_event(
    event_type: str,
    deviation_score: float,
    sensor_payload: dict,
    hour: int,
    day_type: str,
    recent_false_positive_rate: float
) -> dict:
    prompt = f"""You are HomePulse, a household safety AI for elderly users.

A sensor anomaly was detected. Decide if this is worth investigating.

Event type: {event_type}
Deviation score: {deviation_score:.1f}x above baseline
Sensor readings: {sensor_payload}
Time: {hour}:00, {day_type}
Recent false positive rate for this event type: {recent_false_positive_rate:.0%}

Respond with JSON only:
{{"investigate": true/false, "confidence": 0.0-1.0, "reason": "one sentence"}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    import json
    return json.loads(response.content[0].text)


async def reason_about_event(
    sensor_data: dict,
    deviation_score: float,
    image_url: str,
    user_history: dict,
    behavioral_schema: dict,
    hour: int,
    day_type: str
) -> dict:
    prompt = f"""You are HomePulse, a household safety AI for elderly users.

Analyze this household anomaly and determine the appropriate response.

Sensor data: {sensor_data}
Deviation: {deviation_score:.1f}x above baseline
Time: {hour}:00 {day_type}
Cropped image URL: {image_url}
User's recent event history: {user_history}
User behavioral schema: {behavioral_schema}

Respond with JSON only:
{{
  "confirmed_event_type": "STOVE_LEFT_ON|FRIDGE_OPEN|FAUCET_RUNNING|WATER_DRIPPING|IRON_LEFT_ON|APPLIANCE_FAULT|FIRE_RISK|FALL_DETECTED",
  "severity": "LOW|MEDIUM|HIGH|CRITICAL",
  "recommended_action": "one sentence for the user",
  "suggested_service": "plumber|fire_department|appliance_repair|emergency_services|none",
  "reasoning": "two sentences max"
}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    import json
    return json.loads(response.content[0].text)


async def write_alert_email(
    event_type: str,
    severity: str,
    recommended_action: str,
    sensor_readings: dict,
    image_url: str,
    user_name: str,
    cancel_window_seconds: int
) -> str:
    prompt = f"""Write a warm, clear HTML email alert for {user_name}, an elderly user.

Event: {event_type.replace('_', ' ').title()}
Severity: {severity}
Recommended action: {recommended_action}
Sensor readings: {sensor_readings}
Image URL: {image_url}
Cancel window: {cancel_window_seconds} seconds

Requirements:
- Warm, simple language — no technical jargon
- Large readable text suggestions in the HTML
- Include the cropped image
- Include severity badge (red for HIGH/CRITICAL, orange for MEDIUM)
- Include cancel option if not CRITICAL
- Keep it concise — elderly users should understand it at a glance
- Return only the HTML body content, no <html> or <body> tags"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


async def write_weekly_digest(
    events: list,
    user_name: str,
    caregiver_name: str = None
) -> str:
    prompt = f"""Write a warm, readable weekly home safety digest for {user_name}.
{"This is being sent to caregiver: " + caregiver_name if caregiver_name else ""}

Events this week: {events}

Requirements:
- Plain, friendly language
- Summarize what happened (don't list every event — find patterns)
- Highlight any recurring issues
- Give 1-2 gentle actionable recommendations
- End on a reassuring note
- Return only HTML body content"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text
```

---

## Anomaly Detection

```python
# app/services/anomaly_detector.py

async def score_reading(user_id: str, payload: SensorPayload, db) -> AnomalyResult:
    hour = payload.timestamp.hour
    day_type = "weekend" if payload.timestamp.weekday() >= 5 else "weekday"

    baseline = await db.sensor_baselines.find_one({
        "user_id": ObjectId(user_id),
        "hour_of_day": hour,
        "day_type": day_type
    })
    if not baseline:
        return AnomalyResult(triggered=False, reason="no_baseline")

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    multiplier = user.get("threshold_multiplier", 2.5)

    # Temperature check
    temp_dev = abs(payload.temperature_c - baseline["temperature"]["mean"])
    if temp_dev > multiplier * baseline["temperature"]["std_dev"]:
        score = temp_dev / baseline["temperature"]["std_dev"]
        return AnomalyResult(
            triggered=True,
            event_type=classify_temp_event(payload),
            deviation_score=score,
            severity=compute_severity(score),
            sensor="temperature"
        )

    # Sound check
    sound_dev = abs(payload.sound_level - baseline["sound_level"]["mean"])
    if sound_dev > multiplier * baseline["sound_level"]["std_dev"]:
        score = sound_dev / baseline["sound_level"]["std_dev"]
        return AnomalyResult(
            triggered=True,
            event_type=classify_sound_event(payload),
            deviation_score=score,
            severity=compute_severity(score),
            sensor="sound"
        )

    return AnomalyResult(triggered=False)


def compute_severity(deviation_score: float) -> str:
    if deviation_score >= 15: return "CRITICAL"
    if deviation_score >= 8:  return "HIGH"
    if deviation_score >= 4:  return "MEDIUM"
    return "LOW"

def classify_temp_event(payload) -> str:
    accel_mag = (payload.accel_x**2 + payload.accel_y**2 + payload.accel_z**2)**0.5
    if accel_mag < 0.5:
        return "STOVE_LEFT_ON" if payload.temperature_c > 40 else "IRON_LEFT_ON"
    return "FIRE_RISK"

def classify_sound_event(payload) -> str:
    if 300 < payload.sound_level < 500: return "FAUCET_RUNNING"
    if payload.sound_level < 300:       return "WATER_DRIPPING"
    return "APPLIANCE_FAULT"
```

---

## FetchAI Agent Patterns

### Base pattern — every agent
```python
from uagents import Agent, Context
from uagents.protocols.chat import ChatProtocol, ChatMessage
from app.config import settings

agent = Agent(name="homepulse_sensor", seed=settings.FETCHAI_AGENT_SEED + "_sensor")
agent.include(ChatProtocol())  # MANDATORY for Agentverse/hackathon

@agent.on_message(ChatMessage)
async def handle_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatMessage(content=f"HomePulse {agent.name} online"))
```

### sensor_agent
```python
@sensor_agent.on_interval(period=5.0)
async def read_and_score(ctx: Context):
    reading = get_latest_reading()      # from serial_reader queue
    if not reading:
        return
    result = await score_reading(DEFAULT_USER_ID, reading, db)
    if result.triggered:
        await ctx.send(TRIAGE_AGENT_ADDRESS, IrregularityEvent(
            user_id=DEFAULT_USER_ID,
            event_type=result.event_type,
            severity=result.severity,
            deviation_score=result.deviation_score,
            sensor_payload=reading.dict()
        ))
    # Update heartbeat timestamp
    await db.agent_heartbeats.update_one(
        {"agent": "sensor_agent"},
        {"$set": {"last_seen": datetime.utcnow()}},
        upsert=True
    )
```

### triage_agent
```python
@triage_agent.on_message(IrregularityEvent)
async def triage(ctx: Context, sender: str, msg: IrregularityEvent):
    schema = await db.behavioral_schema.find_one({"user_id": ObjectId(msg.user_id)})
    fp_rate = schema["event_type_history"].get(
        msg.event_type, {}
    ).get("false_positive_rate", 0.2)

    result = await claude_service.triage_event(
        event_type=msg.event_type,
        deviation_score=msg.deviation_score,
        sensor_payload=msg.sensor_payload,
        hour=datetime.utcnow().hour,
        day_type="weekend" if datetime.utcnow().weekday() >= 5 else "weekday",
        recent_false_positive_rate=fp_rate
    )

    if not result["investigate"]:
        await db.events.insert_one({...dismissed event doc...})
        return

    # Fire history and vision in parallel
    triage_result = TriageResult(user_id=msg.user_id, event=msg, confidence=result["confidence"])
    await ctx.send(HISTORY_AGENT_ADDRESS, triage_result)
    await ctx.send(VISION_AGENT_ADDRESS, triage_result)
```

### monitor_agent — waits for both parallel results
```python
# Use a simple in-memory cache keyed by event_id to collect both results
pending_events = {}  # event_id → {history: None, vision: None}

@monitor_agent.on_message(UserHistoryContext)
async def got_history(ctx: Context, sender: str, msg: UserHistoryContext):
    pending_events.setdefault(msg.event_id, {})["history"] = msg
    await try_reason(ctx, msg.event_id)

@monitor_agent.on_message(VisionResult)
async def got_vision(ctx: Context, sender: str, msg: VisionResult):
    pending_events.setdefault(msg.event_id, {})["vision"] = msg
    await try_reason(ctx, msg.event_id)

async def try_reason(ctx: Context, event_id: str):
    data = pending_events.get(event_id, {})
    if "history" not in data or "vision" not in data:
        return  # still waiting for the other

    history = data["history"]
    vision = data["vision"]
    del pending_events[event_id]

    decision = await claude_service.reason_about_event(
        sensor_data=history.sensor_payload,
        deviation_score=history.deviation_score,
        image_url=vision.cropped_url,
        user_history=history.recent_events,
        behavioral_schema=history.behavioral_schema,
        hour=datetime.utcnow().hour,
        day_type="weekend" if datetime.utcnow().weekday() >= 5 else "weekday"
    )

    # Write event to MongoDB
    event_id_db = await write_event_to_db(history, vision, decision)

    await ctx.send(ESCALATION_AGENT_ADDRESS, MonitorDecision(
        event_id=event_id_db,
        user_id=history.user_id,
        severity=decision["severity"],
        suggested_service=decision["suggested_service"],
        recommended_action=decision["recommended_action"],
        image_url=vision.cropped_url
    ))
```

### escalation_agent
```python
@escalation_agent.on_message(MonitorDecision)
async def escalate(ctx: Context, sender: str, msg: MonitorDecision):
    user = await db.users.find_one({"_id": ObjectId(msg.user_id)})

    recipients = [user["email"]]
    if msg.severity in ("HIGH", "CRITICAL"):
        for contact in user.get("emergency_contacts", []):
            recipients.append(contact["email"])

    cancel_window = 0 if msg.severity == "CRITICAL" else settings.CANCEL_WINDOW_SECONDS

    await ctx.send(NOTIFICATION_AGENT_ADDRESS, EscalationOrder(
        event_id=msg.event_id,
        user_id=msg.user_id,
        recipients=recipients,
        severity=msg.severity,
        suggested_service=msg.suggested_service,
        recommended_action=msg.recommended_action,
        image_url=msg.image_url,
        cancel_window_seconds=cancel_window
    ))
```

### heartbeat_agent
```python
@heartbeat_agent.on_interval(period=60.0)
async def check_heartbeat(ctx: Context):
    record = await db.agent_heartbeats.find_one({"agent": "sensor_agent"})
    if not record:
        return
    last_seen = record["last_seen"]
    silence_seconds = (datetime.utcnow() - last_seen).total_seconds()

    if silence_seconds > settings.HEARTBEAT_TIMEOUT_SECONDS:
        user = await db.users.find_one({"_id": ObjectId(settings.DEFAULT_USER_ID)})
        await gmail_service.send_system_offline_alert(user)
```

### report_agent
```python
@report_agent.on_interval(period=60 * 60 * 24 * 7)  # 7 days
async def send_weekly_report(ctx: Context):
    cutoff = datetime.utcnow() - timedelta(days=7)
    events = await db.events.find({
        "user_id": ObjectId(settings.DEFAULT_USER_ID),
        "detected_at": {"$gte": cutoff}
    }).to_list(100)

    user = await db.users.find_one({"_id": ObjectId(settings.DEFAULT_USER_ID)})
    digest_html = await claude_service.write_weekly_digest(events, user["name"])

    all_recipients = [user["email"]] + [c["email"] for c in user.get("emergency_contacts", [])]
    await gmail_service.send_weekly_digest(all_recipients, digest_html)
```

---

## Gmail Service

```python
# app/services/gmail_service.py
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.config import settings

def _send(to_addresses: list[str], subject: str, html_body: str) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.GMAIL_ADDRESS
    msg["To"] = ", ".join(to_addresses)
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(settings.GMAIL_ADDRESS, settings.GMAIL_APP_PASSWORD)
            server.sendmail(settings.GMAIL_ADDRESS, to_addresses, msg.as_string())
        return True
    except Exception as e:
        print(f"Gmail error: {e}")
        return False

async def send_alert(user: dict, event: dict, email_body: str) -> bool:
    subject = f"[HomePulse {event['severity']}] {event['event_type'].replace('_',' ').title()} detected"
    return _send([user["email"]], subject, email_body)

async def send_to_contact(contact: dict, event: dict, email_body: str) -> bool:
    subject = f"[HomePulse] Alert for {event.get('user_name', 'your loved one')}"
    return _send([contact["email"]], subject, email_body)

async def send_weekly_digest(recipients: list[str], digest_html: str) -> bool:
    return _send(recipients, "HomePulse Weekly Safety Digest", digest_html)

async def send_system_offline_alert(user: dict) -> bool:
    body = "<h2>⚠️ HomePulse System Offline</h2><p>Your HomePulse sensor has gone silent. Please check the device.</p>"
    return _send([user["email"]], "[HomePulse] Sensor offline", body)
```

---

## Cloudinary Service

```python
# app/services/cloudinary_service.py
import cloudinary, cloudinary.uploader, cloudinary.utils
import cv2, numpy as np
from app.config import settings

cloudinary.config(
    cloud_name=settings.CLOUDINARY_CLOUD_NAME,
    api_key=settings.CLOUDINARY_API_KEY,
    api_secret=settings.CLOUDINARY_API_SECRET
)

async def upload_and_crop(frame: np.ndarray, event_id: str, zone: dict) -> dict:
    _, buffer = cv2.imencode(".jpg", frame)
    raw = cloudinary.uploader.upload(
        buffer.tobytes(),
        public_id=f"homepulse/raw/{event_id}",
        resource_type="image"
    )
    cropped_url = cloudinary.utils.cloudinary_url(
        f"homepulse/raw/{event_id}",
        transformation=[
            {"crop": "crop", "x": zone["x"], "y": zone["y"], "width": zone["w"], "height": zone["h"]},
            {"effect": "sharpen:80"},
            {"effect": "improve"}
        ]
    )[0]
    return {"raw_url": raw["secure_url"], "cropped_url": cropped_url}
```

---

## Agent Addresses

After first run of each agent, print `agent.address` and store in `agents/agent_messages.py`:

```python
# agents/agent_messages.py
SENSOR_AGENT_ADDRESS      = "agent1q..."
TRIAGE_AGENT_ADDRESS      = "agent1q..."
HISTORY_AGENT_ADDRESS     = "agent1q..."
VISION_AGENT_ADDRESS      = "agent1q..."
MONITOR_AGENT_ADDRESS     = "agent1q..."
ESCALATION_AGENT_ADDRESS  = "agent1q..."
NOTIFICATION_AGENT_ADDRESS = "agent1q..."
LEARNING_AGENT_ADDRESS    = "agent1q..."
REPORT_AGENT_ADDRESS      = "agent1q..."
HEARTBEAT_AGENT_ADDRESS   = "agent1q..."
```

---

## Demo Setup Checklist

- [ ] Run `scripts/seed_demo.py` — creates demo user, baselines, room zones
- [ ] Run `scripts/register_agents.py` — prints all agent addresses, paste into `agent_messages.py`
- [ ] Test Arduino serial: `scripts/test_serial.py`
- [ ] Verify webcam index 0: quick OpenCV test
- [ ] Verify Cloudinary: test upload one frame
- [ ] Verify Gmail: send one test email
- [ ] Start all 10 agents
- [ ] Start FastAPI: `uvicorn app.main:app --reload`
- [ ] Trigger demo scenario → confirm email arrives with cropped image
- [ ] Show MongoDB updating live (behavioral_schema, events collections)
- [ ] Show Agentverse dashboard with all agents registered
